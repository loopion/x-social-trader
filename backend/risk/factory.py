"""Builds a fully wired `RiskManager` from `Settings` + market calendar."""

from __future__ import annotations

from backend.core.settings import Settings
from backend.risk.manager import RiskManager
from backend.risk.market_calendar import ExchangeCalendarsAdapter, MarketCalendar
from backend.risk.rules import (
    DailyDrawdownRule,
    IdempotencyRule,
    MarketHoursRule,
    MaxTradesPerDayRule,
    PositionSizeRule,
    TotalExposureRule,
)


def build_risk_manager(
    settings: Settings,
    calendar: MarketCalendar | None = None,
) -> RiskManager:
    """Assemble the canonical rule set from env-backed settings.

    Pass ``calendar`` to inject a stub in tests; production code passes None
    and receives the real `exchange_calendars` adapter.
    """
    cal = calendar if calendar is not None else ExchangeCalendarsAdapter(settings.market)
    rules = (
        PositionSizeRule(max_position_pct=settings.max_position_pct),
        TotalExposureRule(max_total_exposure_pct=settings.max_total_exposure_pct),
        MaxTradesPerDayRule(max_trades_per_day=settings.max_trades_per_day),
        DailyDrawdownRule(max_drawdown_pct=settings.max_daily_drawdown_pct),
        MarketHoursRule(calendar=cal, allow_after_hours=settings.allow_after_hours),
        IdempotencyRule(),
    )
    return RiskManager(rules=rules)
