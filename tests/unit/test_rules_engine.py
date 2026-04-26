"""Rule engine deterministic-evaluation tests (RULE-02)."""

from __future__ import annotations

from typing import Any

from backend.models.enums import OrderSide, OrderType, RuleOutcome, TradingMode
from backend.rules.engine import RuleEngine
from backend.rules.models import ActionSpec, ConditionSpec, RuleSpec


class _FakeEvent:
    """Minimal stand-in for ``backend.models.event.Event`` — only the engine
    pokes at the four condition fields + ``event_id`` + ``ticker``."""

    def __init__(
        self,
        *,
        event_id: str = "ev1",
        intent: str = "bullish",
        ticker: str = "TSLA",
        confidence: float = 0.8,
        time_horizon: str = "swing",
    ) -> None:
        self.event_id = event_id
        self.intent = intent
        self.ticker = ticker
        self.confidence = confidence
        self.time_horizon = time_horizon


def _action(strategy_id: str = "s1") -> ActionSpec:
    return ActionSpec(
        trading_mode=TradingMode.PAPER,
        side=OrderSide.BUY,
        order_type=OrderType.MARKET,
        quantity=1,
        reference_price_usd=100.0,
        strategy_id=strategy_id,
    )


def _rule(
    *,
    rid: str,
    priority: int,
    conditions: list[dict[str, Any]] | None = None,
    enabled: bool = True,
) -> RuleSpec:
    conds = conditions or [{"field": "intent", "op": "eq", "value": "bullish"}]
    return RuleSpec(
        id=rid,
        priority=priority,
        enabled=enabled,
        conditions=[ConditionSpec(**c) for c in conds],
        action=_action(strategy_id=rid),
    )


# --- First-match wins -----------------------------------------------------


def test_first_match_wins_when_priority_ties() -> None:
    rules = [
        _rule(rid="b", priority=10),  # both match — 'a' wins by id tiebreak
        _rule(rid="a", priority=10),
    ]
    outcome = RuleEngine(rules).evaluate(_FakeEvent())  # type: ignore[arg-type]
    assert outcome.matched is not None
    assert outcome.matched.rule_id == "a"
    # Both rules touched: 1 matched + 1 skipped.
    assert {e.outcome for e in outcome.evaluations} == {
        RuleOutcome.MATCHED,
        RuleOutcome.SKIPPED,
    }


def test_higher_priority_evaluates_first() -> None:
    rules = [
        _rule(rid="lo", priority=10),
        _rule(rid="hi", priority=99),
    ]
    outcome = RuleEngine(rules).evaluate(_FakeEvent())  # type: ignore[arg-type]
    assert outcome.matched is not None
    assert outcome.matched.rule_id == "hi"


# --- Conditions ----------------------------------------------------------


def test_all_conditions_must_pass() -> None:
    rule = _rule(
        rid="r",
        priority=10,
        conditions=[
            {"field": "intent", "op": "eq", "value": "bullish"},
            {"field": "confidence", "op": "gte", "value": 0.9},  # event has 0.8
        ],
    )
    outcome = RuleEngine([rule]).evaluate(_FakeEvent())  # type: ignore[arg-type]
    assert outcome.matched is None
    assert outcome.evaluations[0].outcome is RuleOutcome.SKIPPED


def test_in_op_against_list_value() -> None:
    rule = _rule(
        rid="r",
        priority=10,
        conditions=[
            {"field": "time_horizon", "op": "in", "value": ["intraday", "swing"]},
        ],
    )
    outcome = RuleEngine([rule]).evaluate(_FakeEvent())  # type: ignore[arg-type]
    assert outcome.matched is not None


def test_neq_and_lt_ops() -> None:
    rule = _rule(
        rid="r",
        priority=10,
        conditions=[
            {"field": "intent", "op": "neq", "value": "noise"},
            {"field": "confidence", "op": "lt", "value": 0.95},
        ],
    )
    outcome = RuleEngine([rule]).evaluate(_FakeEvent(confidence=0.5))  # type: ignore[arg-type]
    assert outcome.matched is not None


# --- Disabled rules + failure modes --------------------------------------


def test_disabled_rule_is_skipped_without_evaluation() -> None:
    rule = _rule(rid="r", priority=10, enabled=False)
    outcome = RuleEngine([rule]).evaluate(_FakeEvent(intent="noise"))  # type: ignore[arg-type]
    assert outcome.matched is None
    record = outcome.evaluations[0]
    assert record.outcome is RuleOutcome.SKIPPED
    assert record.inputs["rule_enabled"] is False


def test_in_op_with_non_list_value_records_failed() -> None:
    bad_rule = _rule(
        rid="r",
        priority=10,
        conditions=[{"field": "ticker", "op": "in", "value": "TSLA"}],
    )
    outcome = RuleEngine([bad_rule]).evaluate(_FakeEvent())  # type: ignore[arg-type]
    assert outcome.matched is None
    assert outcome.evaluations[0].outcome is RuleOutcome.FAILED


# --- ProposedOrder projection --------------------------------------------


def test_matched_record_carries_proposed_order() -> None:
    rule = _rule(rid="hit", priority=50)
    event = _FakeEvent(event_id="evX", ticker="AAPL")
    outcome = RuleEngine([rule]).evaluate(event)  # type: ignore[arg-type]
    assert outcome.matched is not None
    proposed = outcome.matched.proposed_order
    assert proposed is not None
    assert proposed.event_id == "evX"
    assert proposed.symbol == "AAPL"
    assert proposed.strategy_id == "hit"


def test_no_rules_returns_empty_outcome() -> None:
    outcome = RuleEngine([]).evaluate(_FakeEvent())  # type: ignore[arg-type]
    assert outcome.matched is None
    assert outcome.evaluations == ()
