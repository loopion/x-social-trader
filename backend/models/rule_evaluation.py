from __future__ import annotations

from sqlalchemy import JSON, CheckConstraint, ForeignKey, Integer, String
from sqlalchemy.orm import Mapped, mapped_column

from backend.models.base import Base, TimestampMixin
from backend.models.enums import RuleOutcome


class RuleEvaluation(Base, TimestampMixin):
    """Audit row (INV-4) — append-only. Records each rule evaluation for replay."""

    __tablename__ = "rule_evaluations"
    __table_args__ = (
        CheckConstraint(
            "outcome IN ('"
            f"{RuleOutcome.MATCHED}', '{RuleOutcome.SKIPPED}', '{RuleOutcome.FAILED}')",
            name="outcome_valid",
        ),
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    event_id: Mapped[str] = mapped_column(
        ForeignKey("events.event_id", ondelete="RESTRICT"), nullable=False, index=True
    )
    rule_id: Mapped[str] = mapped_column(String(64), nullable=False, index=True)
    rule_priority: Mapped[int] = mapped_column(Integer, nullable=False)
    inputs_hash: Mapped[str] = mapped_column(String(64), nullable=False)
    inputs_json: Mapped[dict] = mapped_column(JSON, nullable=False)  # type: ignore[type-arg]
    outcome: Mapped[str] = mapped_column(String(16), nullable=False)
    # Non-null when outcome == matched; encodes the ProposedOrder template.
    proposed_order_json: Mapped[dict | None] = mapped_column(JSON)  # type: ignore[type-arg]
