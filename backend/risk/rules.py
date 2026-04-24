"""Individual risk rules (RISK-01).

Every rule implements the `RiskRule` Protocol: one cheap, pure `check(order, ctx)`
call returning a `RuleCheckResult`. No state, no I/O, no side effects — the
rule manager is the only place that hits the DB (RISK-02).

Rule order is stable for determinism: rules that short-circuit (idempotence,
kill-switch-relevant) are still evaluated individually — no early return,
so callers see **every** failure in `ValidationResult.failures`.
"""

from __future__ import annotations

from typing import Protocol

from backend.risk.market_calendar import MarketCalendar
from backend.risk.models import ProposedOrder, RuleCheckResult, ValidationContext


class RiskRule(Protocol):
    """A single check — stateless beyond construction-time config."""

    name: str

    def check(self, order: ProposedOrder, context: ValidationContext) -> RuleCheckResult: ...


# -----------------------------------------------------------------------------
# Helpers
# -----------------------------------------------------------------------------


def _order_notional_usd(order: ProposedOrder) -> float:
    return order.quantity * order.reference_price_usd


# -----------------------------------------------------------------------------
# Rules
# -----------------------------------------------------------------------------


class PositionSizeRule:
    """Order notional (|qty * price|) ≤ max_position_pct of capital."""

    name = "position_size"

    def __init__(self, max_position_pct: float) -> None:
        self._max = max_position_pct

    def check(self, order: ProposedOrder, context: ValidationContext) -> RuleCheckResult:
        notional = _order_notional_usd(order)
        limit_usd = (self._max / 100.0) * context.account_capital_usd
        inputs = {
            "notional_usd": notional,
            "limit_usd": limit_usd,
            "max_position_pct": self._max,
            "account_capital_usd": context.account_capital_usd,
        }
        if notional > limit_usd:
            return RuleCheckResult.failing(
                self.name,
                f"notional {notional:.2f} USD exceeds {limit_usd:.2f} USD "
                f"({self._max}% of {context.account_capital_usd:.2f})",
                **inputs,
            )
        return RuleCheckResult.passing(self.name, **inputs)


class TotalExposureRule:
    """current_total_exposure + order_notional ≤ max_total_exposure_pct of capital."""

    name = "total_exposure"

    def __init__(self, max_total_exposure_pct: float) -> None:
        self._max = max_total_exposure_pct

    def check(self, order: ProposedOrder, context: ValidationContext) -> RuleCheckResult:
        notional = _order_notional_usd(order)
        projected = context.total_exposure_usd + notional
        limit_usd = (self._max / 100.0) * context.account_capital_usd
        inputs = {
            "notional_usd": notional,
            "current_exposure_usd": context.total_exposure_usd,
            "projected_exposure_usd": projected,
            "limit_usd": limit_usd,
            "max_total_exposure_pct": self._max,
        }
        if projected > limit_usd:
            return RuleCheckResult.failing(
                self.name,
                f"projected exposure {projected:.2f} USD "
                f"exceeds {limit_usd:.2f} USD ({self._max}% cap)",
                **inputs,
            )
        return RuleCheckResult.passing(self.name, **inputs)


class MaxTradesPerDayRule:
    """trades_today < max_trades_per_day (this order would be the next one)."""

    name = "max_trades_per_day"

    def __init__(self, max_trades_per_day: int) -> None:
        self._max = max_trades_per_day

    def check(self, order: ProposedOrder, context: ValidationContext) -> RuleCheckResult:
        inputs = {"trades_today": context.trades_today, "max_trades_per_day": self._max}
        if context.trades_today >= self._max:
            return RuleCheckResult.failing(
                self.name,
                f"{context.trades_today} trades already today (cap {self._max})",
                **inputs,
            )
        return RuleCheckResult.passing(self.name, **inputs)


class DailyDrawdownRule:
    """drawdown from daily peak ≤ max_daily_drawdown_pct.

    Breach here must also trigger the kill switch (KILL-05) — that wiring
    lives in the executor + kill-switch service; this rule just blocks the
    order and emits a reason loud enough for KILL-05 to pick up.
    """

    name = "daily_drawdown"

    def __init__(self, max_drawdown_pct: float) -> None:
        self._max = max_drawdown_pct

    def check(self, order: ProposedOrder, context: ValidationContext) -> RuleCheckResult:
        peak = context.daily_peak_usd
        pnl = context.daily_pnl_usd
        drawdown_pct = 0.0 if peak <= 0 else max(0.0, (peak - (peak + pnl)) / peak * 100.0)
        inputs = {
            "daily_peak_usd": peak,
            "daily_pnl_usd": pnl,
            "drawdown_pct": drawdown_pct,
            "max_drawdown_pct": self._max,
        }
        if drawdown_pct >= self._max:
            return RuleCheckResult.failing(
                self.name,
                f"drawdown {drawdown_pct:.2f}% ≥ cap {self._max}% — KILL-05 trigger",
                **inputs,
            )
        return RuleCheckResult.passing(self.name, **inputs)


class MarketHoursRule:
    """Order rejected outside the market session unless `allow_after_hours`.

    Calendar is injected (see `market_calendar.MarketCalendar`) so tests can
    run without loading the real exchange_calendars data.
    """

    name = "market_hours"

    def __init__(self, calendar: MarketCalendar, allow_after_hours: bool) -> None:
        self._cal = calendar
        self._allow = allow_after_hours

    def check(self, order: ProposedOrder, context: ValidationContext) -> RuleCheckResult:
        inputs = {"allow_after_hours": self._allow, "ts": context.now.isoformat()}
        if self._allow:
            return RuleCheckResult.passing(self.name, reason="after-hours allowed", **inputs)
        if self._cal.is_open_at(context.now):
            return RuleCheckResult.passing(self.name, **inputs)
        return RuleCheckResult.failing(self.name, "market is closed at order time", **inputs)


class IdempotencyRule:
    """Same event_id / idempotency_key must never produce a second order (INV-6)."""

    name = "idempotency"

    def check(self, order: ProposedOrder, context: ValidationContext) -> RuleCheckResult:
        inputs = {"event_id": order.event_id, "strategy_id": order.strategy_id}
        if order.event_id in context.seen_event_ids:
            return RuleCheckResult.failing(
                self.name, f"event_id {order.event_id!r} already produced an order", **inputs
            )
        expected_key = f"{order.event_id}:{order.strategy_id}"
        if expected_key in context.seen_idempotency_keys:
            return RuleCheckResult.failing(
                self.name,
                f"idempotency_key {expected_key!r} already used",
                **inputs,
            )
        return RuleCheckResult.passing(self.name, **inputs)
