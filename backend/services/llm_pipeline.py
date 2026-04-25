"""LLM pipeline worker (LLM-02 + LLM-03 + LLM-04).

Consumes the Redis queue ``raw_tweets`` populated by ``run_ingestion``,
analyses each tweet with an injected ``LLMProvider``, persists the audit
row to ``llm_decisions`` (INV-4), and — if the decision is non-noise —
fans out one ``events`` row per resolved ticker before pushing event ids
onto the ``events`` queue for the rule engine (phase 9).

For each tweet:
1. Pre-check kill switch.
2. ``LPOP`` the next id (or block briefly).
3. Load the ``raw_tweets`` row, build a ``RawTweet`` DTO.
4. Call ``provider.analyze`` — never raises, parser fallbacks to noise.
5. Persist ``llm_decisions`` row (always, even on invalid_json — INV-4).
6. Charge the daily LLM budget; on breach activate kill switch and stop.
7. If ``intent != noise``: resolve tickers via aliases, persist one
   ``events`` row per ticker, ``RPUSH`` event ids to ``events`` queue.

Sessions: short-lived ``AsyncSession`` per iteration (mirrors
``run_ingestion`` so a stalled worker never holds a connection).
"""

from __future__ import annotations

import os
from collections.abc import Awaitable
from dataclasses import dataclass
from typing import Any, cast

from redis.asyncio import Redis
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from backend.core.logging import get_logger
from backend.kill_switch import KillSwitchService
from backend.kill_switch.service import EnvGetter
from backend.models.enums import Intent, LLMDecisionStatus
from backend.models.event import Event as DBEvent
from backend.models.llm_decision import LLMDecision as DBLLMDecision
from backend.models.raw_tweet import RawTweet as DBRawTweet
from backend.providers.base import LLMProvider, RawTweet
from backend.services.aliases import resolve_tickers
from backend.services.llm_budget import LLMBudgetTracker, trigger_from_llm_budget

log = get_logger("services.llm_pipeline")

REDIS_INPUT_QUEUE = "raw_tweets"
REDIS_OUTPUT_QUEUE = "events"


def _default_env_getter() -> str | None:
    return os.environ.get("KILL_SWITCH")


@dataclass(frozen=True, slots=True)
class LLMPipelineReport:
    analyzed: int
    invalid_json: int
    events_published: int
    stopped_reason: str | None  # None when the queue drained cleanly


def _to_dto(row: DBRawTweet) -> RawTweet:
    return RawTweet(
        tweet_id=row.tweet_id,
        x_user_id=row.x_user_id,
        username=row.username,
        content=row.content,
        lang=row.lang,
        raw_json=row.raw_json,
        received_at=row.received_at,
    )


def _build_event_id(tweet_id: str, ticker: str) -> str:
    """One event per (tweet, ticker). Stable for INV-6 idempotency."""
    return f"{tweet_id}:{ticker}"


async def run_llm_pipeline(
    *,
    provider: LLMProvider,
    session_factory: async_sessionmaker[AsyncSession],
    redis_client: Redis,
    budget: LLMBudgetTracker,
    env_getter: EnvGetter = _default_env_getter,
    drain: bool = False,
    block_timeout_seconds: int = 1,
) -> LLMPipelineReport:
    """Consume the queue until kill switch / budget breach / drain.

    ``drain=True`` means "process whatever is currently queued and return"
    — used by tests so the function always terminates. In production the
    worker runs with ``drain=False`` and blocks on ``BLPOP`` indefinitely.
    """
    analyzed = 0
    invalid_json = 0
    events_published = 0
    stopped_reason: str | None = None

    while True:
        # 1. Kill-switch pre-check (per-iteration session — see ingestion.py).
        async with session_factory() as session:
            kill_switch = KillSwitchService(
                session=session, redis_client=redis_client, env_getter=env_getter
            )
            state = await kill_switch.is_active()
        if state.active:
            stopped_reason = f"kill_switch_active:{state.source}"
            log.warning("llm_pipeline.stopped_kill_switch", source=state.source)
            break

        # 2. Pop next tweet id.
        raw_id = await _pop(redis_client, drain=drain, block_seconds=block_timeout_seconds)
        if raw_id is None:
            if drain:
                break
            continue

        try:
            db_id = int(raw_id)
        except ValueError:
            log.warning("llm_pipeline.bad_queue_payload", payload=raw_id)
            continue

        # 3. Load tweet + analyze + persist.
        async with session_factory() as session:
            tweet_row = await session.get(DBRawTweet, db_id)
            if tweet_row is None:
                log.warning("llm_pipeline.tweet_not_found", db_id=db_id)
                continue
            tweet_dto = _to_dto(tweet_row)
            result = await provider.analyze(tweet_dto)
            decision_row = DBLLMDecision(
                raw_tweet_id=tweet_row.id,
                prompt_version=result.decision.prompt_version,
                model=result.decision.model,
                provider=result.provider,
                prompt=result.prompt,
                raw_response=result.raw_response,
                parsed_decision=result.decision.model_dump(mode="json"),
                cost_usd=result.decision.cost_usd,
                latency_ms=result.decision.latency_ms,
                status=result.status.value,
            )
            session.add(decision_row)
            await session.flush()
            decision_db_id = decision_row.id

            new_event_ids: list[str] = []
            if result.decision.intent is not Intent.NOISE:
                tickers = await resolve_tickers(result.decision.tickers, session=session)
                for ticker in tickers:
                    event_id = _build_event_id(tweet_dto.tweet_id, ticker)
                    # INV-6: idempotent — the unique constraint guards reruns.
                    exists = (
                        await session.execute(
                            select(DBEvent.id).where(DBEvent.event_id == event_id)
                        )
                    ).scalar_one_or_none()
                    if exists is not None:
                        continue
                    session.add(
                        DBEvent(
                            event_id=event_id,
                            raw_tweet_id=tweet_row.id,
                            llm_decision_id=decision_db_id,
                            ticker=ticker,
                            intent=result.decision.intent.value,
                            confidence=result.decision.confidence,
                            time_horizon=result.decision.time_horizon.value,
                        )
                    )
                    new_event_ids.append(event_id)
            await session.commit()

        analyzed += 1
        if result.status is LLMDecisionStatus.INVALID_JSON:
            invalid_json += 1

        # 4. Publish events to the rule-engine queue (post-commit so a
        # crash mid-pipeline cannot publish phantom events).
        for event_id in new_event_ids:
            await cast(
                "Awaitable[Any]",
                redis_client.rpush(REDIS_OUTPUT_QUEUE, event_id),
            )
        events_published += len(new_event_ids)

        # 5. Charge the daily budget. Break out if breached.
        status = await budget.record_call(cost_usd=result.decision.cost_usd)
        if status.over_budget:
            async with session_factory() as session:
                kill_switch = KillSwitchService(
                    session=session,
                    redis_client=redis_client,
                    env_getter=env_getter,
                )
                activated = await trigger_from_llm_budget(kill_switch, status=status)
                await session.commit()
            if activated:
                stopped_reason = f"llm_budget_breached:{status.spend_usd:.4f}_USD"
                log.error(
                    "llm_pipeline.stopped_budget_breached",
                    day=status.day,
                    spend_usd=status.spend_usd,
                    limit_usd=status.limit_usd,
                )
                break

    return LLMPipelineReport(
        analyzed=analyzed,
        invalid_json=invalid_json,
        events_published=events_published,
        stopped_reason=stopped_reason,
    )


async def _pop(redis_client: Redis, *, drain: bool, block_seconds: int) -> str | None:
    """Pop one queued tweet id; ``None`` when nothing is available."""
    if drain:
        raw = await cast("Awaitable[Any]", redis_client.lpop(REDIS_INPUT_QUEUE))
    else:
        raw = await cast(
            "Awaitable[Any]",
            redis_client.blpop([REDIS_INPUT_QUEUE], timeout=block_seconds),
        )
        if raw is not None:
            # blpop returns (queue, value); we want value.
            _, raw = raw
    if raw is None:
        return None
    if isinstance(raw, bytes):
        return raw.decode()
    return str(raw)


__all__ = [
    "REDIS_INPUT_QUEUE",
    "REDIS_OUTPUT_QUEUE",
    "LLMPipelineReport",
    "run_llm_pipeline",
]
