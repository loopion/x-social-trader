"""RULE-04 — E2E paper golden path.

Wires the full LLM pipeline → rule engine → executor → broker chain on
top of a single fake tweet, then asserts that the ``trade_journal``
view joins everything end-to-end.

Order of events:
1. Seed the alias map (Tesla → TSLA) + a single bullish_swing rule on disk.
2. Insert a `raw_tweets` row + push its id onto the LLM input queue.
3. Run `run_llm_pipeline` with a mock provider returning bullish TSLA;
   the pipeline persists `llm_decisions`, fans out to `events`, and
   pushes the event id onto the `events` queue.
4. Run `run_rule_pipeline` (drain mode); the engine matches the rule,
   submits via `OrderExecutor`, the mock broker records the order.
5. Simulate a broker fill, persist it via `persist_fill`.
6. SELECT * FROM trade_journal → exactly one fully-joined row.

Budget: under 30s per CA — the test runs in well under a second.
"""

from __future__ import annotations

from collections.abc import Awaitable
from datetime import UTC, datetime
from pathlib import Path
from typing import Any, cast

import fakeredis.aioredis
import pytest
from sqlalchemy import select, text
from sqlalchemy.ext.asyncio import AsyncEngine

from backend.core.settings import Settings
from backend.db.session import build_session_factory
from backend.execution.executor import OrderExecutor, persist_fill
from backend.kill_switch import KillSwitchService
from backend.models.alias import Alias
from backend.models.enums import Intent, TimeHorizon
from backend.models.event import Event as DBEvent
from backend.models.order import Order as DBOrder
from backend.models.raw_tweet import RawTweet as DBRawTweet
from backend.providers.base import LLMDecision
from backend.risk import RiskManager
from backend.risk.factory import build_risk_manager
from backend.rules.store import RuleStore
from backend.services.llm_budget import LLMBudgetTracker
from backend.services.llm_pipeline import REDIS_INPUT_QUEUE as LLM_QUEUE
from backend.services.llm_pipeline import run_llm_pipeline
from backend.services.rule_pipeline import run_rule_pipeline
from tests.mocks import MockBrokerProvider, MockLLMProvider

RULE_YAML = """
id: bullish_swing_paper
priority: 100
enabled: true
description: Reference RULE-04 fixture.
conditions:
  - field: intent
    op: eq
    value: bullish
  - field: confidence
    op: gte
    value: 0.6
  - field: time_horizon
    op: in
    value: [intraday, swing]
action:
  trading_mode: paper
  side: buy
  order_type: market
  quantity: 1
  reference_price_usd: 100.0
  strategy_id: bullish_swing_paper
"""


class _AlwaysOpen:
    """Phase-9 E2E happens at any wall-clock time → market is always open."""

    def is_open_at(self, _ts: datetime) -> bool:
        return True


@pytest.fixture
def fake_redis() -> fakeredis.aioredis.FakeRedis:
    return fakeredis.aioredis.FakeRedis()


@pytest.fixture
def rule_store(tmp_path: Path) -> RuleStore:
    (tmp_path / "rule.yaml").write_text(RULE_YAML, encoding="utf-8")
    store = RuleStore(tmp_path)
    store.reload()
    return store


async def test_tweet_to_fill_via_paper_pipeline(
    engine: AsyncEngine,
    fake_redis: fakeredis.aioredis.FakeRedis,
    rule_store: RuleStore,
) -> None:
    factory = build_session_factory(engine)

    # 1. Seed: alias + raw tweet.
    async with factory() as session:
        session.add(Alias(mention="Tesla", ticker="TSLA", priority=10))
        await session.flush()
        tweet_row = DBRawTweet(
            tweet_id="goldenpath-1",
            x_user_id="u1",
            username="alice",
            content="Tesla bullish gigafactory news",
            lang="en",
            raw_json={},
            received_at=datetime.now(UTC),
        )
        session.add(tweet_row)
        await session.commit()
        tweet_db_id: int = tweet_row.id

    await cast(
        "Awaitable[Any]",
        fake_redis.rpush(LLM_QUEUE, str(tweet_db_id)),
    )

    # 2. LLM pipeline — mock provider returns bullish TSLA / swing.
    bullish = LLMDecision(
        tickers=["Tesla"],  # alias resolution will canonicalise to TSLA
        intent=Intent.BULLISH,
        confidence=0.78,
        time_horizon=TimeHorizon.SWING,
        reasoning="gigafactory boost",
        model="mock",
        prompt_version="v1",
    )
    llm_provider = MockLLMProvider(responses={"goldenpath-1": bullish})
    llm_budget = LLMBudgetTracker(redis_client=fake_redis, limit_usd=10.0)
    llm_report = await run_llm_pipeline(
        provider=llm_provider,
        session_factory=factory,
        redis_client=fake_redis,
        budget=llm_budget,
        env_getter=lambda: None,
        drain=True,
    )
    assert llm_report.events_published == 1, llm_report

    # 3. Rule pipeline — engine matches, executor submits via mock broker.
    broker = MockBrokerProvider(
        account_summary={"NetLiquidation": 50_000.0},
        positions=[],
    )
    await broker.connect()
    settings = Settings(_env_file=None)  # type: ignore[call-arg]
    risk: RiskManager = build_risk_manager(settings, calendar=_AlwaysOpen())

    def _executor_factory(session: Any) -> OrderExecutor:
        ks = KillSwitchService(session=session, redis_client=fake_redis, env_getter=lambda: None)
        return OrderExecutor(broker=broker, risk_manager=risk, kill_switch=ks, settings=settings)

    rule_report = await run_rule_pipeline(
        rule_store=rule_store,
        executor_factory=_executor_factory,
        broker=broker,
        session_factory=factory,
        redis_client=fake_redis,
        env_getter=lambda: None,
        drain=True,
    )
    assert rule_report.evaluated == 1
    assert rule_report.matched == 1
    assert rule_report.submitted == 1
    assert rule_report.rejected == 0
    assert len(broker.placed) == 1
    assert broker.placed[0].symbol == "TSLA"

    # 4. Simulate fill + persist.
    placed = broker.placed[0]
    receipt = broker.receipts[0]
    async with factory() as session:
        db_order = (
            await session.execute(
                select(DBOrder).where(DBOrder.idempotency_key == placed.idempotency_key)
            )
        ).scalar_one()
        broker_fill = broker.simulate_fill(
            receipt,
            quantity=1,
            price=101.0,
            commission_usd=0.5,
        )
        await persist_fill(broker_fill, db_order, session)
        await session.commit()

    # 5. trade_journal view — fully joined row.
    async with factory() as session:
        rows = (
            (
                await session.execute(
                    text("SELECT * FROM trade_journal WHERE tweet_id = :t"),
                    {"t": "goldenpath-1"},
                )
            )
            .mappings()
            .all()
        )
    assert len(rows) == 1
    row = rows[0]
    assert row["ticker"] == "TSLA"
    assert row["intent"] == "bullish"
    assert row["order_symbol"] == "TSLA"
    assert row["order_quantity"] == 1
    assert row["fill_price"] == 101.0
    assert row["external_fill_id"] == broker_fill.external_fill_id
    assert row["llm_prompt_version"] == "v1"
    # Event id is derived from tweet+ticker — INV-6.
    async with factory() as session:
        ev = (
            await session.execute(select(DBEvent).where(DBEvent.event_id == row["event_id"]))
        ).scalar_one()
    assert ev.event_id == "goldenpath-1:TSLA"
