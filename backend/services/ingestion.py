"""Ingestion orchestrator (ING-02 + ING-04).

For each streamed tweet:
1. Persist to `raw_tweets` **before** any downstream processing (durability).
2. Deduplicate via the UNIQUE(tweet_id) constraint — duplicates are swallowed.
3. Push the resulting DB id to the Redis queue ``raw_tweets`` so the LLM
   worker (phase 8) can consume.
4. Record one unit of spend with the budget tracker; on breach trigger the
   kill switch and stop the loop.

Backpressure: if the Redis queue depth climbs above
``BACKPRESSURE_WARN_THRESHOLD`` we log a warning but keep going — dropping
tweets is worse than a slow pipeline.

Sessions: one short-lived ``AsyncSession`` per tweet iteration so a stalled
loop never holds a connection. The kill-switch service is rebuilt per-session
to keep its DB handle live (it would otherwise leak when the session closed).
"""

from __future__ import annotations

import os
from collections.abc import Awaitable
from dataclasses import asdict, dataclass
from typing import Any, cast

from redis.asyncio import Redis
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from backend.core.logging import get_logger
from backend.core.metrics import tweets_ingested_total
from backend.kill_switch import KillSwitchService
from backend.kill_switch.service import EnvGetter
from backend.models.raw_tweet import RawTweet as DBRawTweet
from backend.providers.base import RawTweet, SocialFeedProvider
from backend.services.twitterapi_budget import (
    TwitterApiBudgetTracker,
    trigger_from_budget,
)

log = get_logger("services.ingestion")

REDIS_QUEUE_KEY = "raw_tweets"
BACKPRESSURE_WARN_THRESHOLD = 1000


def _default_env_getter() -> str | None:
    return os.environ.get("KILL_SWITCH")


@dataclass(frozen=True, slots=True)
class IngestionReport:
    persisted: int
    duplicates: int
    stopped_reason: str | None  # None if cancelled externally


async def _persist_raw_tweet(session: AsyncSession, tweet: RawTweet) -> int | None:
    """Insert a raw_tweets row. Returns id, or None if a duplicate (tweet_id UNIQUE)."""
    row = DBRawTweet(
        tweet_id=tweet.tweet_id,
        x_user_id=tweet.x_user_id,
        username=tweet.username,
        content=tweet.content,
        lang=tweet.lang,
        raw_json=tweet.raw_json,
        received_at=tweet.received_at,
    )
    session.add(row)
    try:
        await session.flush()
    except IntegrityError:
        await session.rollback()
        return None
    return row.id


async def run_ingestion(
    *,
    provider: SocialFeedProvider,
    accounts: list[str],
    session_factory: async_sessionmaker[AsyncSession],
    redis_client: Redis,
    budget: TwitterApiBudgetTracker,
    env_getter: EnvGetter = _default_env_getter,
) -> IngestionReport:
    """Main loop. Returns when budget is breached, kill switch activates, or
    the provider's async iterator exhausts (tests / controlled shutdown)."""
    persisted = 0
    duplicates = 0
    stopped_reason: str | None = None

    async for tweet in provider.subscribe(accounts):
        # 1. Kill switch pre-check + persist within a single short-lived session.
        async with session_factory() as session:
            kill_switch = KillSwitchService(
                session=session, redis_client=redis_client, env_getter=env_getter
            )
            state = await kill_switch.is_active()
            if state.active:
                stopped_reason = f"kill_switch_active:{state.source}"
                log.warning("ingestion.stopped_kill_switch", source=state.source)
                break

            # 2. Persist BEFORE processing (durability).
            tweet_id = await _persist_raw_tweet(session, tweet)
            await session.commit()

        if tweet_id is None:
            duplicates += 1
            continue
        persisted += 1

        # 3. Publish to Redis queue.
        queue_depth = int(
            await cast(
                "Awaitable[Any]",
                redis_client.rpush(REDIS_QUEUE_KEY, str(tweet_id)),
            )
        )
        if queue_depth > BACKPRESSURE_WARN_THRESHOLD:
            log.warning(
                "ingestion.queue_backpressure",
                depth=queue_depth,
                threshold=BACKPRESSURE_WARN_THRESHOLD,
            )

        # 4. Budget: record spend, activate kill switch if breached.
        status = await budget.record_tweet()
        if status.over_budget:
            async with session_factory() as session:
                kill_switch = KillSwitchService(
                    session=session,
                    redis_client=redis_client,
                    env_getter=env_getter,
                )
                activated = await trigger_from_budget(kill_switch, status=status)
                await session.commit()
            if activated:
                stopped_reason = f"twitterapi_budget_breached:{status.spend_usd:.4f}_USD"
                log.error("ingestion.stopped_budget_breached", **asdict(status))
                break

    tweets_ingested_total.inc(0)  # harmless ping to keep metric present
    return IngestionReport(
        persisted=persisted,
        duplicates=duplicates,
        stopped_reason=stopped_reason,
    )
