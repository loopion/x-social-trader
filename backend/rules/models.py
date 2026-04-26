"""Pydantic schemas for declarative rules (RULE-01).

YAML on disk → ``RuleSpec`` instances. Validation happens once at load
time so a syntactically-bad rule cannot reach the engine. Keep these
models frozen + ``extra="forbid"`` so silent typos in YAML surface as
errors instead of being ignored.
"""

from __future__ import annotations

from typing import Annotated, Any, Literal

from pydantic import BaseModel, ConfigDict, Field

from backend.models.enums import OrderSide, OrderType, TradingMode

ConditionField = Literal["intent", "ticker", "confidence", "time_horizon"]
ConditionOp = Literal["eq", "neq", "gt", "gte", "lt", "lte", "in"]


class ConditionSpec(BaseModel):
    """One predicate over an event field. ``in`` expects a list ``value``."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    field: ConditionField
    op: ConditionOp
    value: Annotated[Any, Field(description="scalar for eq/neq/cmp ops, list for `in`")]


class ActionSpec(BaseModel):
    """Order template the rule emits when its conditions all match.

    ``reference_price_usd`` feeds the risk manager's notional check —
    Phase 9 has no live price feed, so rules carry a fallback. Phase 10
    backtests will inject real prices; later phases can tag the rule
    with a quote source.
    """

    model_config = ConfigDict(frozen=True, extra="forbid")

    trading_mode: TradingMode = TradingMode.PAPER
    side: OrderSide
    order_type: OrderType
    quantity: int = Field(gt=0)
    limit_price: float | None = None
    reference_price_usd: float = Field(gt=0.0)
    strategy_id: str = Field(min_length=1, max_length=64)


class RuleSpec(BaseModel):
    """One YAML rule file → one ``RuleSpec``."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    id: str = Field(min_length=1, max_length=64)
    priority: int
    enabled: bool = True
    description: str = ""
    conditions: list[ConditionSpec] = Field(min_length=1)
    action: ActionSpec
