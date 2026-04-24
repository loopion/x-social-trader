"""Risk-manager inputs + verdict types (RISK-01)."""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime
from typing import Any

from pydantic import BaseModel, ConfigDict, Field

from backend.models.enums import OrderSide, OrderType, TradingMode


class ProposedOrder(BaseModel):
    """Rule-engine output. Passed through `RiskManager.validate` → either blocked
    or converted into a ``ValidatedOrder`` (phase 4 DTO) for the broker.

    ``reference_price_usd`` is the notional basis for size checks:
    - LIMIT orders: caller sets this to `limit_price`.
    - MARKET orders: caller sets this to the latest known mid/last.
    """

    model_config = ConfigDict(frozen=True, extra="forbid")

    event_id: str
    strategy_id: str
    trading_mode: TradingMode
    side: OrderSide
    order_type: OrderType
    symbol: str
    quantity: int = Field(gt=0)
    limit_price: float | None = None
    reference_price_usd: float = Field(gt=0.0)


@dataclass(frozen=True, slots=True)
class ValidationContext:
    """Pre-loaded account snapshot the risk manager evaluates against."""

    now: datetime
    account_capital_usd: float
    total_exposure_usd: float
    trades_today: int
    daily_pnl_usd: float
    daily_peak_usd: float
    seen_event_ids: frozenset[str] = field(default_factory=frozenset)
    seen_idempotency_keys: frozenset[str] = field(default_factory=frozenset)


@dataclass(frozen=True, slots=True)
class RuleCheckResult:
    """One rule's verdict."""

    rule_name: str
    passed: bool
    reason: str = ""
    inputs: dict[str, Any] = field(default_factory=dict)

    @classmethod
    def passing(cls, rule_name: str, **inputs: Any) -> RuleCheckResult:
        return cls(rule_name=rule_name, passed=True, inputs=inputs)

    @classmethod
    def failing(cls, rule_name: str, reason: str, **inputs: Any) -> RuleCheckResult:
        return cls(rule_name=rule_name, passed=False, reason=reason, inputs=inputs)


@dataclass(frozen=True, slots=True)
class ValidationResult:
    """Aggregate verdict — ``ok`` only if every rule passed."""

    checks: tuple[RuleCheckResult, ...]

    @property
    def ok(self) -> bool:
        return all(c.passed for c in self.checks)

    @property
    def failures(self) -> tuple[RuleCheckResult, ...]:
        return tuple(c for c in self.checks if not c.passed)
