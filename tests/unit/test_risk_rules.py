"""Every RISK-01 rule gets at least one pass + one fail — INV-3 coverage target."""

from __future__ import annotations

from datetime import UTC, datetime

from backend.models.enums import OrderSide, OrderType, TradingMode
from backend.risk.models import ProposedOrder, ValidationContext
from backend.risk.rules import (
    DailyDrawdownRule,
    IdempotencyRule,
    MarketHoursRule,
    MaxTradesPerDayRule,
    PositionSizeRule,
    TotalExposureRule,
)

NOW = datetime(2026, 4, 24, 14, 0, tzinfo=UTC)


def _order(
    *,
    quantity: int = 10,
    reference_price_usd: float = 100.0,
    event_id: str = "e1",
    strategy_id: str = "s1",
) -> ProposedOrder:
    return ProposedOrder(
        event_id=event_id,
        strategy_id=strategy_id,
        trading_mode=TradingMode.PAPER,
        side=OrderSide.BUY,
        order_type=OrderType.MARKET,
        symbol="TSLA",
        quantity=quantity,
        reference_price_usd=reference_price_usd,
    )


def _ctx(
    *,
    capital: float = 10_000.0,
    exposure: float = 0.0,
    trades_today: int = 0,
    daily_pnl: float = 0.0,
    daily_peak: float = 10_000.0,
    seen_events: frozenset[str] = frozenset(),
    seen_keys: frozenset[str] = frozenset(),
) -> ValidationContext:
    return ValidationContext(
        now=NOW,
        account_capital_usd=capital,
        total_exposure_usd=exposure,
        trades_today=trades_today,
        daily_pnl_usd=daily_pnl,
        daily_peak_usd=daily_peak,
        seen_event_ids=seen_events,
        seen_idempotency_keys=seen_keys,
    )


class _AlwaysOpen:
    def is_open_at(self, ts: datetime) -> bool:
        return True


class _AlwaysClosed:
    def is_open_at(self, ts: datetime) -> bool:
        return False


# --- PositionSizeRule -------------------------------------------------------


def test_position_size_passes_under_limit() -> None:
    # 10 shares * $100 = $1000 = 10% of $10_000. Cap is 20%.
    result = PositionSizeRule(max_position_pct=20.0).check(_order(), _ctx())
    assert result.passed
    assert result.inputs["notional_usd"] == 1000.0


def test_position_size_fails_over_limit() -> None:
    # 10 * $1000 = $10_000 = 100% of capital. Cap 20%.
    order = _order(reference_price_usd=1000.0)
    result = PositionSizeRule(max_position_pct=20.0).check(order, _ctx())
    assert not result.passed
    assert "exceeds" in result.reason


# --- TotalExposureRule -----------------------------------------------------


def test_total_exposure_passes_when_projected_below_cap() -> None:
    # current $500 + new $1000 = $1500. Cap = 20% of $10_000 = $2000.
    result = TotalExposureRule(max_total_exposure_pct=20.0).check(_order(), _ctx(exposure=500.0))
    assert result.passed


def test_total_exposure_fails_when_projected_over_cap() -> None:
    # current $1500 + new $1000 = $2500 > $2000 cap.
    result = TotalExposureRule(max_total_exposure_pct=20.0).check(_order(), _ctx(exposure=1500.0))
    assert not result.passed
    assert "exposure" in result.reason.lower()


# --- MaxTradesPerDayRule ---------------------------------------------------


def test_max_trades_passes_when_count_below() -> None:
    result = MaxTradesPerDayRule(max_trades_per_day=10).check(_order(), _ctx(trades_today=9))
    assert result.passed


def test_max_trades_fails_when_count_at_limit() -> None:
    # Inclusive: 10 already today, cap is 10 → next trade rejected.
    result = MaxTradesPerDayRule(max_trades_per_day=10).check(_order(), _ctx(trades_today=10))
    assert not result.passed


# --- DailyDrawdownRule -----------------------------------------------------


def test_daily_drawdown_passes_when_within_budget() -> None:
    # peak 10_000, pnl -200 → drawdown 2% ≤ 3% cap.
    result = DailyDrawdownRule(max_drawdown_pct=3.0).check(
        _order(), _ctx(daily_peak=10_000.0, daily_pnl=-200.0)
    )
    assert result.passed


def test_daily_drawdown_fails_when_breached() -> None:
    # peak 10_000, pnl -400 → drawdown 4% ≥ 3% cap.
    result = DailyDrawdownRule(max_drawdown_pct=3.0).check(
        _order(), _ctx(daily_peak=10_000.0, daily_pnl=-400.0)
    )
    assert not result.passed
    assert "KILL-05" in result.reason


def test_daily_drawdown_with_zero_peak_is_never_negative() -> None:
    """Edge case: fresh session, peak not yet established — rule must not crash."""
    result = DailyDrawdownRule(max_drawdown_pct=3.0).check(
        _order(), _ctx(daily_peak=0.0, daily_pnl=0.0)
    )
    assert result.passed


# --- MarketHoursRule -------------------------------------------------------


def test_market_hours_passes_when_open() -> None:
    rule = MarketHoursRule(calendar=_AlwaysOpen(), allow_after_hours=False)
    result = rule.check(_order(), _ctx())
    assert result.passed


def test_market_hours_fails_when_closed() -> None:
    rule = MarketHoursRule(calendar=_AlwaysClosed(), allow_after_hours=False)
    result = rule.check(_order(), _ctx())
    assert not result.passed
    assert "closed" in result.reason.lower()


def test_market_hours_bypassed_by_allow_after_hours() -> None:
    rule = MarketHoursRule(calendar=_AlwaysClosed(), allow_after_hours=True)
    result = rule.check(_order(), _ctx())
    assert result.passed
    assert "after-hours allowed" in result.inputs.get("reason", "")


# --- IdempotencyRule -------------------------------------------------------


def test_idempotency_passes_for_fresh_event() -> None:
    result = IdempotencyRule().check(_order(), _ctx())
    assert result.passed


def test_idempotency_fails_on_repeat_event_id() -> None:
    result = IdempotencyRule().check(
        _order(event_id="repeat"), _ctx(seen_events=frozenset({"repeat"}))
    )
    assert not result.passed
    assert "already produced" in result.reason


def test_idempotency_fails_on_repeat_idempotency_key() -> None:
    # Key shape mirrors EXEC-02: f"{event_id}:{strategy_id}"
    key = "e1:s1"
    result = IdempotencyRule().check(_order(), _ctx(seen_keys=frozenset({key})))
    assert not result.passed
    assert "already used" in result.reason
