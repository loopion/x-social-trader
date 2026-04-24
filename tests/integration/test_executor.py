"""EXEC-01 + EXEC-02 — OrderExecutor enforces INV-1/2/3 and persists."""

from __future__ import annotations

from datetime import UTC, datetime

import fakeredis.aioredis
import pytest
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from backend.core.settings import Settings
from backend.execution import (
    KillSwitchActiveError,
    LiveModeNotPermittedError,
    OrderExecutor,
    SubmissionRejected,
    build_validation_context,
    compute_idempotency_key,
    persist_fill,
)
from backend.kill_switch import KillSwitchService
from backend.models import Fill as DBFill
from backend.models import Order as DBOrder
from backend.models.enums import KillSwitchTrigger, OrderSide, OrderType, TradingMode
from backend.providers import Position
from backend.risk import ProposedOrder, ValidationContext
from backend.risk.factory import build_risk_manager
from tests.mocks import MockBrokerProvider

NOW = datetime(2026, 4, 24, 14, 0, tzinfo=UTC)


class _AlwaysOpen:
    def is_open_at(self, ts: datetime) -> bool:
        return True


@pytest.fixture
def fake_redis() -> fakeredis.aioredis.FakeRedis:
    return fakeredis.aioredis.FakeRedis()


def _proposed(quantity: int = 1, trading_mode: TradingMode = TradingMode.PAPER) -> ProposedOrder:
    return ProposedOrder(
        event_id="e1",
        strategy_id="s1",
        trading_mode=trading_mode,
        side=OrderSide.BUY,
        order_type=OrderType.MARKET,
        symbol="TSLA",
        quantity=quantity,
        reference_price_usd=1.0,
    )


def _ctx() -> ValidationContext:
    return ValidationContext(
        now=NOW,
        account_capital_usd=10_000.0,
        total_exposure_usd=0.0,
        trades_today=0,
        daily_pnl_usd=0.0,
        daily_peak_usd=10_000.0,
    )


def _executor(
    *,
    broker: MockBrokerProvider,
    kill_switch: KillSwitchService,
    settings: Settings | None = None,
) -> OrderExecutor:
    s = settings or Settings(_env_file=None)  # type: ignore[call-arg]
    risk = build_risk_manager(s, calendar=_AlwaysOpen())
    return OrderExecutor(broker=broker, risk_manager=risk, kill_switch=kill_switch, settings=s)


# --- EXEC-02: idempotency key -----------------------------------------------


def test_compute_idempotency_key_is_deterministic() -> None:
    assert compute_idempotency_key("e1", "s1") == "e1:s1"
    assert compute_idempotency_key("e1", "s1") == compute_idempotency_key("e1", "s1")


# --- INV-2 blocks everything ------------------------------------------------


async def test_kill_switch_active_blocks_submit(
    session: AsyncSession, fake_redis: fakeredis.aioredis.FakeRedis
) -> None:
    broker = MockBrokerProvider()
    await broker.connect()
    ks = KillSwitchService(session=session, redis_client=fake_redis, env_getter=lambda: None)
    await ks.activate(trigger=KillSwitchTrigger.MANUAL, actor="test")
    await session.commit()

    executor = _executor(broker=broker, kill_switch=ks)

    with pytest.raises(KillSwitchActiveError):
        await executor.submit(_proposed(), _ctx(), session)

    assert broker.placed == []


# --- INV-1 blocks live without double opt-in --------------------------------


async def test_live_order_without_opt_in_is_rejected(
    session: AsyncSession, fake_redis: fakeredis.aioredis.FakeRedis
) -> None:
    broker = MockBrokerProvider()
    await broker.connect()
    ks = KillSwitchService(session=session, redis_client=fake_redis, env_getter=lambda: None)

    # Default settings: paper_trading=True, trading_mode="paper" → live not permitted.
    executor = _executor(broker=broker, kill_switch=ks)

    with pytest.raises(LiveModeNotPermittedError):
        await executor.submit(_proposed(trading_mode=TradingMode.LIVE), _ctx(), session)

    assert broker.placed == []


async def test_live_order_passes_when_both_flags_flipped(
    session: AsyncSession, fake_redis: fakeredis.aioredis.FakeRedis
) -> None:
    broker = MockBrokerProvider()
    await broker.connect()
    ks = KillSwitchService(session=session, redis_client=fake_redis, env_getter=lambda: None)
    settings = Settings(_env_file=None, trading_mode="live", paper_trading=False)  # type: ignore[call-arg]

    executor = _executor(broker=broker, kill_switch=ks, settings=settings)

    result = await executor.submit(_proposed(trading_mode=TradingMode.LIVE), _ctx(), session)
    await session.commit()
    assert result.receipt.external_id.startswith("EXT-")
    assert broker.placed[0].trading_mode == TradingMode.LIVE


# --- INV-3 blocks when risk says no -----------------------------------------


async def test_risk_manager_rejection_blocks_broker_call(
    session: AsyncSession, fake_redis: fakeredis.aioredis.FakeRedis
) -> None:
    broker = MockBrokerProvider()
    await broker.connect()
    ks = KillSwitchService(session=session, redis_client=fake_redis, env_getter=lambda: None)
    executor = _executor(broker=broker, kill_switch=ks)

    # Capital too small → position size rule will block.
    ctx = ValidationContext(
        now=NOW,
        account_capital_usd=0.01,
        total_exposure_usd=0.0,
        trades_today=0,
        daily_pnl_usd=0.0,
        daily_peak_usd=0.01,
    )
    with pytest.raises(SubmissionRejected, match="risk manager"):
        await executor.submit(_proposed(), ctx, session)

    assert broker.placed == []


# --- Happy path -------------------------------------------------------------


async def test_paper_order_is_submitted_and_persisted(
    session: AsyncSession, fake_redis: fakeredis.aioredis.FakeRedis
) -> None:
    broker = MockBrokerProvider()
    await broker.connect()
    ks = KillSwitchService(session=session, redis_client=fake_redis, env_getter=lambda: None)
    executor = _executor(broker=broker, kill_switch=ks)

    result = await executor.submit(_proposed(), _ctx(), session)
    await session.commit()

    assert result.receipt.idempotency_key == "e1:s1"
    assert len(broker.placed) == 1
    row = (
        await session.execute(select(DBOrder).where(DBOrder.idempotency_key == "e1:s1"))
    ).scalar_one()
    assert row.external_id == result.receipt.external_id
    assert row.symbol == "TSLA"
    assert row.trading_mode == TradingMode.PAPER.value


# --- Fill persistence -------------------------------------------------------


async def test_persist_fill_inserts_audit_row(
    session: AsyncSession, fake_redis: fakeredis.aioredis.FakeRedis
) -> None:
    broker = MockBrokerProvider()
    await broker.connect()
    ks = KillSwitchService(session=session, redis_client=fake_redis, env_getter=lambda: None)
    executor = _executor(broker=broker, kill_switch=ks)

    result = await executor.submit(_proposed(), _ctx(), session)
    broker_fill = broker.simulate_fill(result.receipt, quantity=1, price=1.0)

    db_order = (
        await session.execute(select(DBOrder).where(DBOrder.id == result.db_order_id))
    ).scalar_one()
    fill = await persist_fill(broker_fill, db_order, session)
    await session.commit()

    rows = (await session.execute(select(DBFill))).scalars().all()
    assert [r.id for r in rows] == [fill.id]
    assert fill.external_fill_id == broker_fill.external_fill_id


# --- Context builder --------------------------------------------------------


async def test_build_validation_context_raises_without_capital(
    session: AsyncSession,
) -> None:
    from backend.execution import ValidationContextError

    broker = MockBrokerProvider(account_summary={})  # no NetLiquidation
    await broker.connect()
    with pytest.raises(ValidationContextError, match="NetLiquidation"):
        await build_validation_context(broker=broker, session=session, now=NOW)


async def test_build_validation_context_counts_today_orders(
    session: AsyncSession, fake_redis: fakeredis.aioredis.FakeRedis
) -> None:
    broker = MockBrokerProvider(
        account_summary={"NetLiquidation": 50_000.0},
        positions=[Position(symbol="TSLA", quantity=10, avg_price_usd=100.0)],
    )
    await broker.connect()
    ks = KillSwitchService(session=session, redis_client=fake_redis, env_getter=lambda: None)
    executor = _executor(broker=broker, kill_switch=ks)
    await executor.submit(_proposed(), _ctx(), session)
    await session.commit()

    context = await build_validation_context(broker=broker, session=session, now=NOW)
    assert context.account_capital_usd == 50_000.0
    assert context.total_exposure_usd == 1000.0  # 10 * 100
    assert context.trades_today == 1
    assert "e1" in context.seen_event_ids
    assert "e1:s1" in context.seen_idempotency_keys
