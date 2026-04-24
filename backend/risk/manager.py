"""RiskManager — the sole validator every order traverses (INV-3).

Also persists one `rule_evaluations` row per rule evaluated (RISK-02 + INV-4).
Intentionally small: rule construction lives in `backend.risk.factory`; rule
logic lives in `backend.risk.rules`. This class only aggregates + audits.
"""

from __future__ import annotations

import hashlib
import json
from collections.abc import Sequence

from sqlalchemy.ext.asyncio import AsyncSession

from backend.models.enums import RuleOutcome
from backend.models.rule_evaluation import RuleEvaluation
from backend.risk.models import (
    ProposedOrder,
    RuleCheckResult,
    ValidationContext,
    ValidationResult,
)
from backend.risk.rules import RiskRule


class RiskManager:
    """Runs all configured rules, aggregates results, writes the audit trail."""

    def __init__(self, rules: Sequence[RiskRule]) -> None:
        if not rules:
            raise ValueError("RiskManager requires at least one rule (INV-3)")
        self._rules: tuple[RiskRule, ...] = tuple(rules)

    @property
    def rules(self) -> tuple[RiskRule, ...]:
        return self._rules

    async def validate(
        self,
        order: ProposedOrder,
        context: ValidationContext,
        session: AsyncSession,
    ) -> ValidationResult:
        """Evaluate every rule, persist one `rule_evaluations` row per rule."""
        checks = tuple(rule.check(order, context) for rule in self._rules)
        result = ValidationResult(checks=checks)
        await self._audit(order, checks, session)
        return result

    async def _audit(
        self,
        order: ProposedOrder,
        checks: tuple[RuleCheckResult, ...],
        session: AsyncSession,
    ) -> None:
        for idx, check in enumerate(checks):
            outcome = RuleOutcome.MATCHED if check.passed else RuleOutcome.FAILED
            payload = {
                "reason": check.reason,
                "order_symbol": order.symbol,
                "order_quantity": order.quantity,
                **check.inputs,
            }
            session.add(
                RuleEvaluation(
                    event_id=order.event_id,
                    rule_id=f"risk.{check.rule_name}",
                    rule_priority=idx,
                    inputs_hash=_hash_json(payload),
                    inputs_json=payload,
                    outcome=outcome.value,
                    proposed_order_json=None,
                )
            )
        await session.flush()


def _hash_json(obj: object) -> str:
    raw = json.dumps(obj, sort_keys=True, default=str).encode()
    return hashlib.sha256(raw).hexdigest()
