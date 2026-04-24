"""RISK-02 — `RiskManager.validate` writes one rule_evaluations row per rule (INV-4)."""

from __future__ import annotations

from datetime import UTC, datetime

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from backend.core.settings import Settings
from backend.models import Event, LLMDecision, RawTweet, RuleEvaluation
from backend.models.enums import OrderSide, OrderType, RuleOutcome, TradingMode
from backend.risk.factory import build_risk_manager
from backend.risk.models import ProposedOrder, ValidationContext


class _AlwaysOpen:
    def is_open_at(self, ts: datetime) -> bool:
        return True


async def _setup_event(session: AsyncSession, event_id: str = "e1") -> None:
    """Create the FK chain raw_tweet → llm_decision → event so audit FKs hold."""
    tweet = RawTweet(
        tweet_id="t-" + event_id,
        x_user_id="x",
        username="u",
        content="c",
        raw_json={},
        received_at=datetime.now(UTC),
    )
    session.add(tweet)
    await session.flush()

    decision = LLMDecision(
        raw_tweet_id=tweet.id,
        prompt_version="v1",
        model="m",
        provider="p",
        prompt="",
        raw_response="{}",
        status="success",
    )
    session.add(decision)
    await session.flush()

    session.add(
        Event(
            event_id=event_id,
            raw_tweet_id=tweet.id,
            llm_decision_id=decision.id,
            ticker="TSLA",
            intent="bullish",
            confidence=0.9,
            time_horizon="intraday",
        )
    )
    await session.commit()


def _order(event_id: str = "e1") -> ProposedOrder:
    # 1 * $1 = $1 notional vs 2% cap of $10_000 context capital = $200 → passes.
    return ProposedOrder(
        event_id=event_id,
        strategy_id="s1",
        trading_mode=TradingMode.PAPER,
        side=OrderSide.BUY,
        order_type=OrderType.MARKET,
        symbol="TSLA",
        quantity=1,
        reference_price_usd=1.0,
    )


def _ctx() -> ValidationContext:
    return ValidationContext(
        now=datetime(2026, 4, 24, 14, 0, tzinfo=UTC),
        account_capital_usd=10_000.0,
        total_exposure_usd=0.0,
        trades_today=0,
        daily_pnl_usd=0.0,
        daily_peak_usd=10_000.0,
    )


async def test_validate_writes_one_row_per_rule(session: AsyncSession) -> None:
    await _setup_event(session)
    manager = build_risk_manager(
        Settings(_env_file=None),  # type: ignore[call-arg]
        calendar=_AlwaysOpen(),
    )

    result = await manager.validate(_order(), _ctx(), session)
    await session.commit()

    assert result.ok
    rows = (await session.execute(select(RuleEvaluation))).scalars().all()
    assert len(rows) == len(manager.rules)
    assert {r.rule_id for r in rows} == {f"risk.{r.name}" for r in manager.rules}
    assert all(r.outcome == RuleOutcome.MATCHED for r in rows)


async def test_validate_records_failed_rules_with_reason(session: AsyncSession) -> None:
    await _setup_event(session)
    # Force position-size to fail by setting capital extremely low.
    ctx = ValidationContext(
        now=datetime(2026, 4, 24, 14, 0, tzinfo=UTC),
        account_capital_usd=10.0,
        total_exposure_usd=0.0,
        trades_today=0,
        daily_pnl_usd=0.0,
        daily_peak_usd=10.0,
    )
    manager = build_risk_manager(
        Settings(_env_file=None),  # type: ignore[call-arg]
        calendar=_AlwaysOpen(),
    )
    result = await manager.validate(_order(), ctx, session)
    await session.commit()

    assert not result.ok
    rows = (await session.execute(select(RuleEvaluation))).scalars().all()
    failed = [r for r in rows if r.outcome == RuleOutcome.FAILED]
    assert any(r.rule_id == "risk.position_size" for r in failed)
    assert any("exceeds" in (r.inputs_json or {}).get("reason", "") for r in failed)


async def test_inputs_hash_is_sha256_hex(session: AsyncSession) -> None:
    """Sanity: audit rows carry a stable-looking sha256 fingerprint."""
    await _setup_event(session)
    manager = build_risk_manager(
        Settings(_env_file=None),  # type: ignore[call-arg]
        calendar=_AlwaysOpen(),
    )
    await manager.validate(_order(), _ctx(), session)
    await session.commit()

    rows = (await session.execute(select(RuleEvaluation))).scalars().all()
    for r in rows:
        assert len(r.inputs_hash) == 64
        int(r.inputs_hash, 16)  # raises ValueError if not hex
