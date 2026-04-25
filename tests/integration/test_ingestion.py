"""Ingestion orchestrator (ING-02 persistence + ING-04 publish + budget stop)."""

from __future__ import annotations

from collections.abc import AsyncIterator, Awaitable
from datetime import UTC, datetime
from typing import Any, cast

import fakeredis.aioredis
import pytest
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncEngine

from backend.db.session import build_session_factory
from backend.models import RawTweet as DBRawTweet
from backend.providers import RawTweet
from backend.services.ingestion import REDIS_QUEUE_KEY, run_ingestion
from backend.services.twitterapi_budget import TwitterApiBudgetTracker


@pytest.fixture
def fake_redis() -> fakeredis.aioredis.FakeRedis:
    return fakeredis.aioredis.FakeRedis()


class _ScriptedProvider:
    """Minimal SocialFeedProvider that yields pre-built tweets and terminates."""

    def __init__(self, tweets: list[RawTweet]) -> None:
        self._tweets = tweets

    async def subscribe(self, accounts: list[str]) -> AsyncIterator[RawTweet]:
        for t in self._tweets:
            yield t


def _tweet(i: int) -> RawTweet:
    return RawTweet(
        tweet_id=f"t{i}",
        x_user_id="u1",
        username="alice",
        content=f"msg {i}",
        raw_json={},
        received_at=datetime.now(UTC),
    )


async def test_happy_path_persists_and_publishes_each_tweet(
    engine: AsyncEngine,
    fake_redis: fakeredis.aioredis.FakeRedis,
) -> None:
    factory = build_session_factory(engine)
    tracker = TwitterApiBudgetTracker(
        redis_client=fake_redis, cost_per_tweet_usd=0.001, limit_usd=100.0
    )

    provider = _ScriptedProvider([_tweet(1), _tweet(2), _tweet(3)])
    report = await run_ingestion(
        provider=provider,
        accounts=["alice"],
        session_factory=factory,
        redis_client=fake_redis,
        budget=tracker,
        env_getter=lambda: None,
    )

    assert report.persisted == 3
    assert report.duplicates == 0
    assert report.stopped_reason is None

    async with factory() as session:
        rows = (await session.execute(select(DBRawTweet))).scalars().all()
    assert sorted(r.tweet_id for r in rows) == ["t1", "t2", "t3"]

    # Queue contains 3 ids in FIFO order.
    depth = int(await cast("Awaitable[Any]", fake_redis.llen(REDIS_QUEUE_KEY)))
    assert depth == 3


async def test_duplicates_are_swallowed_via_unique_constraint(
    engine: AsyncEngine,
    fake_redis: fakeredis.aioredis.FakeRedis,
) -> None:
    factory = build_session_factory(engine)
    tracker = TwitterApiBudgetTracker(
        redis_client=fake_redis, cost_per_tweet_usd=0.001, limit_usd=100.0
    )

    provider = _ScriptedProvider([_tweet(1), _tweet(1), _tweet(2)])
    report = await run_ingestion(
        provider=provider,
        accounts=["alice"],
        session_factory=factory,
        redis_client=fake_redis,
        budget=tracker,
        env_getter=lambda: None,
    )
    assert report.persisted == 2
    assert report.duplicates == 1


async def test_budget_breach_stops_and_activates_kill_switch(
    engine: AsyncEngine,
    fake_redis: fakeredis.aioredis.FakeRedis,
) -> None:
    factory = build_session_factory(engine)
    # cost_per = 1.0, limit = 1.0 → first tweet breaches and triggers kill switch.
    tracker = TwitterApiBudgetTracker(
        redis_client=fake_redis, cost_per_tweet_usd=1.0, limit_usd=1.0
    )

    provider = _ScriptedProvider([_tweet(1), _tweet(2), _tweet(3)])
    report = await run_ingestion(
        provider=provider,
        accounts=["alice"],
        session_factory=factory,
        redis_client=fake_redis,
        budget=tracker,
        env_getter=lambda: None,
    )
    # t1 persists (spend 1.0 → over), kill switch fires, loop exits before t2.
    assert report.persisted == 1
    assert report.stopped_reason is not None
    assert "twitterapi_budget" in report.stopped_reason


async def test_kill_switch_preemptively_active_stops_loop(
    engine: AsyncEngine,
    fake_redis: fakeredis.aioredis.FakeRedis,
) -> None:
    factory = build_session_factory(engine)
    tracker = TwitterApiBudgetTracker(
        redis_client=fake_redis, cost_per_tweet_usd=0.001, limit_usd=100.0
    )

    provider = _ScriptedProvider([_tweet(1), _tweet(2)])
    report = await run_ingestion(
        provider=provider,
        accounts=["alice"],
        session_factory=factory,
        redis_client=fake_redis,
        budget=tracker,
        env_getter=lambda: "1",  # KILL_SWITCH=1 → tri-source returns env active.
    )
    assert report.persisted == 0
    assert report.stopped_reason is not None
    assert "kill_switch_active" in report.stopped_reason
