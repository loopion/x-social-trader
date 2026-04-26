"""Rule engine — deterministic priority-ordered evaluation (RULE-02).

Inputs: a sequence of validated ``RuleSpec`` and one ``Event`` (DB row
shape — see ``backend.models.event.Event``). Output:

* a list of ``RuleEvaluationRecord`` covering every rule examined (for
  the ``rule_evaluations`` audit table — INV-4), and
* the matched rule's ``ProposedOrder`` template (or ``None``).

Strategy: priority-descending, ``id``-ascending tiebreak, "first match
wins". Rules with ``enabled=False`` produce a ``skipped`` record without
running their conditions. Conditions raising on type mismatch produce
``failed`` records — never crash the worker.
"""

from __future__ import annotations

import hashlib
import json
from dataclasses import dataclass
from typing import Any

from backend.core.logging import get_logger
from backend.models.enums import RuleOutcome
from backend.models.event import Event as DBEvent
from backend.risk import ProposedOrder
from backend.rules.models import ConditionSpec, RuleSpec

log = get_logger("rules.engine")


def _event_field(event: DBEvent, name: str) -> Any:
    return getattr(event, name)


def _check(condition: ConditionSpec, event: DBEvent) -> bool:
    actual = _event_field(event, condition.field)
    op = condition.op
    val = condition.value
    if op == "eq":
        return bool(actual == val)
    if op == "neq":
        return bool(actual != val)
    if op == "gt":
        return float(actual) > float(val)
    if op == "gte":
        return float(actual) >= float(val)
    if op == "lt":
        return float(actual) < float(val)
    if op == "lte":
        return float(actual) <= float(val)
    if op == "in":
        if not isinstance(val, list):
            raise TypeError(f"`in` op requires a list value, got {type(val).__name__}")
        return actual in val
    raise ValueError(f"unsupported op: {op}")


@dataclass(frozen=True, slots=True)
class RuleEvaluationRecord:
    """One row to write into ``rule_evaluations`` (INV-4 audit)."""

    rule_id: str
    rule_priority: int
    inputs: dict[str, Any]
    inputs_hash: str
    outcome: RuleOutcome
    proposed_order: ProposedOrder | None  # only on MATCHED


@dataclass(frozen=True, slots=True)
class RuleEngineOutcome:
    """Aggregate engine output for one event."""

    matched: RuleEvaluationRecord | None  # None when no rule matched
    evaluations: tuple[RuleEvaluationRecord, ...]


def _hash_inputs(inputs: dict[str, Any]) -> str:
    blob = json.dumps(inputs, sort_keys=True, default=str).encode()
    return hashlib.sha256(blob).hexdigest()


def build_proposed_order(rule: RuleSpec, event: DBEvent) -> ProposedOrder:
    """Project a matched rule onto a ``ProposedOrder`` for the executor.

    ``symbol`` comes from the event ticker, ``event_id`` from the event
    itself. The risk manager + INV-1/2/3 still gate the actual order
    placement downstream.
    """
    return ProposedOrder(
        event_id=event.event_id,
        strategy_id=rule.action.strategy_id,
        trading_mode=rule.action.trading_mode,
        side=rule.action.side,
        order_type=rule.action.order_type,
        symbol=event.ticker,
        quantity=rule.action.quantity,
        limit_price=rule.action.limit_price,
        reference_price_usd=rule.action.reference_price_usd,
    )


class RuleEngine:
    """Stateless evaluator. Inject a fresh ``RuleStore.get_rules()`` snapshot."""

    def __init__(self, rules: list[RuleSpec]) -> None:
        # Defensive copy + canonical sort so engine is order-independent.
        self._rules = sorted(list(rules), key=lambda r: (-r.priority, r.id))

    def evaluate(self, event: DBEvent) -> RuleEngineOutcome:
        records: list[RuleEvaluationRecord] = []
        matched: RuleEvaluationRecord | None = None

        for rule in self._rules:
            inputs = {
                "intent": event.intent,
                "ticker": event.ticker,
                "confidence": event.confidence,
                "time_horizon": event.time_horizon,
                "rule_conditions": [c.model_dump() for c in rule.conditions],
                "rule_enabled": rule.enabled,
            }
            inputs_hash = _hash_inputs(inputs)

            if not rule.enabled:
                records.append(
                    RuleEvaluationRecord(
                        rule_id=rule.id,
                        rule_priority=rule.priority,
                        inputs=inputs,
                        inputs_hash=inputs_hash,
                        outcome=RuleOutcome.SKIPPED,
                        proposed_order=None,
                    )
                )
                continue

            try:
                conditions_met = all(_check(c, event) for c in rule.conditions)
            except (TypeError, ValueError) as exc:
                log.warning(
                    "rules.engine.rule_failed",
                    rule_id=rule.id,
                    error=type(exc).__name__,
                    detail=str(exc)[:200],
                )
                records.append(
                    RuleEvaluationRecord(
                        rule_id=rule.id,
                        rule_priority=rule.priority,
                        inputs=inputs,
                        inputs_hash=inputs_hash,
                        outcome=RuleOutcome.FAILED,
                        proposed_order=None,
                    )
                )
                continue

            if matched is None and conditions_met:
                matched = RuleEvaluationRecord(
                    rule_id=rule.id,
                    rule_priority=rule.priority,
                    inputs=inputs,
                    inputs_hash=inputs_hash,
                    outcome=RuleOutcome.MATCHED,
                    proposed_order=build_proposed_order(rule, event),
                )
                records.append(matched)
            else:
                records.append(
                    RuleEvaluationRecord(
                        rule_id=rule.id,
                        rule_priority=rule.priority,
                        inputs=inputs,
                        inputs_hash=inputs_hash,
                        outcome=RuleOutcome.SKIPPED,
                        proposed_order=None,
                    )
                )

        return RuleEngineOutcome(matched=matched, evaluations=tuple(records))
