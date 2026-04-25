"""LLM pipeline worker (LLM-02 + LLM-03 + LLM-04)."""

from __future__ import annotations

from collections.abc import Awaitable
from datetime import UTC, datetime
from typing import Any, cast

import fakeredis.aioredis
import pytest
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncEngine

from backend.db.session import build_session_factory
from backend.models.alias import Alias
from backend.models.enums import Intent, LLMDecisionStatus, TimeHorizon
from backend.models.event import Event as DBEvent
from backend.models.llm_decision import LLMDecision as DBLLMDecision
from backend.models.raw_tweet import RawTweet as DBRawTweet
from backend.providers.base import LLMAnalysisResult, LLMDecision, RawTweet
from backend.services.llm_budget import LLMBudgetTracker
from backend.services.llm_pipeline import (
    REDIS_INPUT_QUEUE,
    REDIS_OUTPUT_QUEUE,
    run_llm_pipeline,
)

# --- Helpers --------------------------------------------------------------


@pytest.fixture
def fake_redis() -> fakeredis.aioredis.FakeRedis:
    return fakeredis.aioredis.FakeRedis()


def _decision(
    *,
    intent: Intent = Intent.BULLISH,
    tickers: list[str] | None = None,
    cost: float = 0.0,
) -> LLMDecision:
    return LLMDecision(
        tickers=tickers if tickers is not None else ["TSLA"],
        intent=intent,
        confidence=0.7,
        time_horizon=TimeHorizon.SWING,
        reasoning="x",
        model="x-social-trader",
        prompt_version="v1",
        cost_usd=cost,
        latency_ms=100,
    )


def _result(
    *,
    decision: LLMDecision,
    status: LLMDecisionStatus = LLMDecisionStatus.SUCCESS,
    raw: str = '{"ok": true}',
) -> LLMAnalysisResult:
    return LLMAnalysisResult(
        decision=decision,
        prompt="prompt-text",
        raw_response=raw,
        status=status,
        provider="openai_compatible",
    )


class _ScriptedProvider:
    """Returns scripted LLMAnalysisResult values in order; raises if exhausted."""

    def __init__(self, results: list[LLMAnalysisResult]) -> None:
        self._results = list(results)
        self.calls = 0

    async def analyze(self, _tweet: RawTweet) -> LLMAnalysisResult:
        self.calls += 1
        if not self._results:
            raise AssertionError("provider script exhausted")
        return self._results.pop(0)


async def _seed_tweet(factory: Any, tweet_id: str = "t1", username: str = "alice") -> int:
    async with factory() as session:
        row = DBRawTweet(
            tweet_id=tweet_id,
            x_user_id="u1",
            username=username,
            content=f"hello {tweet_id}",
            lang="en",
            raw_json={},
            received_at=datetime.now(UTC),
        )
        session.add(row)
        await session.commit()
        return row.id


async def _push(redis_client: fakeredis.aioredis.FakeRedis, db_id: int) -> None:
    await cast(
        "Awaitable[Any]",
        redis_client.rpush(REDIS_INPUT_QUEUE, str(db_id)),
    )


# --- Happy path -----------------------------------------------------------


async def test_happy_path_persists_decision_and_publishes_events(
    engine: AsyncEngine, fake_redis: fakeredis.aioredis.FakeRedis
) -> None:
    factory = build_session_factory(engine)
    tweet_id = await _seed_tweet(factory)
    await _push(fake_redis, tweet_id)

    provider = _ScriptedProvider([_result(decision=_decision(tickers=["TSLA"], cost=0.0001))])
    tracker = LLMBudgetTracker(redis_client=fake_redis, limit_usd=10.0)

    report = await run_llm_pipeline(
        provider=provider,
        session_factory=factory,
        redis_client=fake_redis,
        budget=tracker,
        env_getter=lambda: None,
        drain=True,
    )

    assert report.analyzed == 1
    assert report.invalid_json == 0
    assert report.events_published == 1
    assert report.stopped_reason is None

    async with factory() as session:
        decisions = (await session.execute(select(DBLLMDecision))).scalars().all()
        events = (await session.execute(select(DBEvent))).scalars().all()
    assert len(decisions) == 1
    assert decisions[0].status == LLMDecisionStatus.SUCCESS.value
    assert decisions[0].provider == "openai_compatible"
    assert decisions[0].prompt_version == "v1"
    assert len(events) == 1
    assert events[0].ticker == "TSLA"
    assert events[0].event_id == "t1:TSLA"

    # Output queue holds the event id.
    out = await cast("Awaitable[Any]", fake_redis.lpop(REDIS_OUTPUT_QUEUE))
    assert out == b"t1:TSLA"


# --- Noise / invalid JSON paths ------------------------------------------


async def test_noise_decision_persists_but_does_not_publish_events(
    engine: AsyncEngine, fake_redis: fakeredis.aioredis.FakeRedis
) -> None:
    factory = build_session_factory(engine)
    tweet_id = await _seed_tweet(factory, tweet_id="t2")
    await _push(fake_redis, tweet_id)

    provider = _ScriptedProvider([_result(decision=_decision(intent=Intent.NOISE, tickers=[]))])
    tracker = LLMBudgetTracker(redis_client=fake_redis, limit_usd=10.0)

    report = await run_llm_pipeline(
        provider=provider,
        session_factory=factory,
        redis_client=fake_redis,
        budget=tracker,
        env_getter=lambda: None,
        drain=True,
    )

    assert report.analyzed == 1
    assert report.events_published == 0
    async with factory() as session:
        events = (await session.execute(select(DBEvent))).scalars().all()
    assert events == []
    out_depth = await cast("Awaitable[Any]", fake_redis.llen(REDIS_OUTPUT_QUEUE))
    assert out_depth == 0


async def test_invalid_json_status_is_persisted_and_counted(
    engine: AsyncEngine, fake_redis: fakeredis.aioredis.FakeRedis
) -> None:
    factory = build_session_factory(engine)
    tweet_id = await _seed_tweet(factory, tweet_id="t3")
    await _push(fake_redis, tweet_id)

    provider = _ScriptedProvider(
        [
            _result(
                decision=_decision(intent=Intent.NOISE, tickers=[]),
                status=LLMDecisionStatus.INVALID_JSON,
                raw="garbled",
            )
        ]
    )
    tracker = LLMBudgetTracker(redis_client=fake_redis, limit_usd=10.0)

    report = await run_llm_pipeline(
        provider=provider,
        session_factory=factory,
        redis_client=fake_redis,
        budget=tracker,
        env_getter=lambda: None,
        drain=True,
    )

    assert report.invalid_json == 1
    async with factory() as session:
        decisions = (await session.execute(select(DBLLMDecision))).scalars().all()
    assert decisions[0].status == LLMDecisionStatus.INVALID_JSON.value
    assert decisions[0].raw_response == "garbled"


# --- Alias resolution ----------------------------------------------------


async def test_aliases_resolve_lowercase_mentions_into_events(
    engine: AsyncEngine, fake_redis: fakeredis.aioredis.FakeRedis
) -> None:
    factory = build_session_factory(engine)
    async with factory() as session:
        session.add(Alias(mention="Tesla", ticker="TSLA", priority=10))
        await session.commit()

    tweet_id = await _seed_tweet(factory, tweet_id="t4")
    await _push(fake_redis, tweet_id)

    provider = _ScriptedProvider([_result(decision=_decision(tickers=["Tesla"]))])
    tracker = LLMBudgetTracker(redis_client=fake_redis, limit_usd=10.0)

    report = await run_llm_pipeline(
        provider=provider,
        session_factory=factory,
        redis_client=fake_redis,
        budget=tracker,
        env_getter=lambda: None,
        drain=True,
    )

    assert report.events_published == 1
    async with factory() as session:
        events = (await session.execute(select(DBEvent))).scalars().all()
    assert events[0].ticker == "TSLA"
    assert events[0].event_id == "t4:TSLA"


# --- Idempotency (INV-6) -------------------------------------------------


async def test_replaying_same_tweet_does_not_duplicate_events(
    engine: AsyncEngine, fake_redis: fakeredis.aioredis.FakeRedis
) -> None:
    factory = build_session_factory(engine)
    tweet_id = await _seed_tweet(factory, tweet_id="t5")

    tracker = LLMBudgetTracker(redis_client=fake_redis, limit_usd=10.0)

    # Push the same id twice and run pipeline; second pass must not create
    # a duplicate (event_id UNIQUE).
    await _push(fake_redis, tweet_id)
    await _push(fake_redis, tweet_id)

    provider = _ScriptedProvider(
        [
            _result(decision=_decision(tickers=["TSLA"])),
            _result(decision=_decision(tickers=["TSLA"])),
        ]
    )

    report = await run_llm_pipeline(
        provider=provider,
        session_factory=factory,
        redis_client=fake_redis,
        budget=tracker,
        env_getter=lambda: None,
        drain=True,
    )

    assert report.analyzed == 2
    assert report.events_published == 1  # second analyze finds the existing row
    async with factory() as session:
        events = (await session.execute(select(DBEvent))).scalars().all()
    assert len(events) == 1


# --- Budget breach -------------------------------------------------------


async def test_budget_breach_activates_kill_switch_and_stops(
    engine: AsyncEngine, fake_redis: fakeredis.aioredis.FakeRedis
) -> None:
    factory = build_session_factory(engine)
    id1 = await _seed_tweet(factory, tweet_id="b1")
    id2 = await _seed_tweet(factory, tweet_id="b2")
    await _push(fake_redis, id1)
    await _push(fake_redis, id2)

    # First call costs $1, limit is $1 → first call breaches.
    provider = _ScriptedProvider(
        [
            _result(decision=_decision(tickers=["TSLA"], cost=1.0)),
            _result(decision=_decision(tickers=["AAPL"], cost=1.0)),
        ]
    )
    tracker = LLMBudgetTracker(redis_client=fake_redis, limit_usd=1.0)

    report = await run_llm_pipeline(
        provider=provider,
        session_factory=factory,
        redis_client=fake_redis,
        budget=tracker,
        env_getter=lambda: None,
        drain=True,
    )

    assert report.analyzed == 1
    assert report.stopped_reason is not None
    assert "llm_budget_breached" in report.stopped_reason

    # The second tweet is still in the queue (we stopped before consuming it).
    out_depth = await cast("Awaitable[Any]", fake_redis.llen(REDIS_INPUT_QUEUE))
    assert out_depth == 1


# --- Kill switch pre-emption ---------------------------------------------


async def test_kill_switch_preempts_pipeline(
    engine: AsyncEngine, fake_redis: fakeredis.aioredis.FakeRedis
) -> None:
    factory = build_session_factory(engine)
    tweet_id = await _seed_tweet(factory, tweet_id="k1")
    await _push(fake_redis, tweet_id)

    provider = _ScriptedProvider([_result(decision=_decision(tickers=["TSLA"]))])
    tracker = LLMBudgetTracker(redis_client=fake_redis, limit_usd=10.0)

    report = await run_llm_pipeline(
        provider=provider,
        session_factory=factory,
        redis_client=fake_redis,
        budget=tracker,
        env_getter=lambda: "1",
        drain=True,
    )

    assert report.analyzed == 0
    assert report.stopped_reason is not None
    assert "kill_switch_active" in report.stopped_reason
    assert provider.calls == 0
