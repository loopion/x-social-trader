"""RiskManager aggregation + factory assembly."""

from __future__ import annotations

from datetime import UTC, datetime

import pytest

from backend.core.settings import Settings
from backend.models.enums import OrderSide, OrderType, TradingMode
from backend.risk.factory import build_risk_manager
from backend.risk.manager import RiskManager
from backend.risk.models import (
    ProposedOrder,
    RuleCheckResult,
    ValidationContext,
    ValidationResult,
)
from backend.risk.rules import RiskRule


class _AlwaysOpen:
    def is_open_at(self, ts: datetime) -> bool:
        return True


class _AlwaysPass:
    name = "always_pass"

    def check(self, order: ProposedOrder, context: ValidationContext) -> RuleCheckResult:
        return RuleCheckResult.passing(self.name)


class _AlwaysFail:
    name = "always_fail"

    def check(self, order: ProposedOrder, context: ValidationContext) -> RuleCheckResult:
        return RuleCheckResult.failing(self.name, reason="nope")


def _order() -> ProposedOrder:
    return ProposedOrder(
        event_id="e1",
        strategy_id="s1",
        trading_mode=TradingMode.PAPER,
        side=OrderSide.BUY,
        order_type=OrderType.MARKET,
        symbol="TSLA",
        quantity=1,
        reference_price_usd=100.0,
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


def test_risk_manager_requires_at_least_one_rule() -> None:
    with pytest.raises(ValueError, match="at least one rule"):
        RiskManager(rules=[])


def test_factory_wires_all_six_canonical_rules() -> None:
    settings = Settings(_env_file=None)  # type: ignore[call-arg]
    manager = build_risk_manager(settings, calendar=_AlwaysOpen())
    names = {r.name for r in manager.rules}
    assert names == {
        "position_size",
        "total_exposure",
        "max_trades_per_day",
        "daily_drawdown",
        "market_hours",
        "idempotency",
    }


def test_validation_result_ok_only_when_every_rule_passes() -> None:
    rules: list[RiskRule] = [_AlwaysPass(), _AlwaysPass()]
    passing = tuple(r.check(_order(), _ctx()) for r in rules)
    result_ok = ValidationResult(checks=passing)
    assert result_ok.ok
    assert result_ok.failures == ()

    rules_with_fail: list[RiskRule] = [_AlwaysPass(), _AlwaysFail()]
    mixed = tuple(r.check(_order(), _ctx()) for r in rules_with_fail)
    result_mixed = ValidationResult(checks=mixed)
    assert not result_mixed.ok
    assert len(result_mixed.failures) == 1
    assert result_mixed.failures[0].rule_name == "always_fail"


def test_factory_passes_env_overrides_to_rules() -> None:
    settings = Settings(  # type: ignore[call-arg]
        _env_file=None,
        max_position_pct=0.5,
        max_total_exposure_pct=1.0,
        max_trades_per_day=1,
        max_daily_drawdown_pct=0.1,
    )
    manager = build_risk_manager(settings, calendar=_AlwaysOpen())
    # Force a failure everywhere to prove thresholds were applied.
    ctx = ValidationContext(
        now=datetime(2026, 4, 24, 14, 0, tzinfo=UTC),
        account_capital_usd=10_000.0,
        total_exposure_usd=100.0,
        trades_today=5,
        daily_pnl_usd=-1000.0,
        daily_peak_usd=10_000.0,
    )
    # Run each rule synchronously (no DB) — proves thresholds bit.
    outcomes = {rule.name: rule.check(_order(), ctx) for rule in manager.rules}
    assert not outcomes["position_size"].passed
    assert not outcomes["max_trades_per_day"].passed
    assert not outcomes["daily_drawdown"].passed
