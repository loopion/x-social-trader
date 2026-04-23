from __future__ import annotations

from sqlalchemy import Boolean, CheckConstraint, Integer, String, Text
from sqlalchemy.orm import Mapped, mapped_column

from backend.models.base import Base, TimestampMixin
from backend.models.enums import KillSwitchTrigger


class KillSwitchEvent(Base, TimestampMixin):
    """Audit row (INV-4) — kill switch activations + deactivations. Append-only.

    Current kill-switch state is the latest row (KILL-01). Env var and Redis
    cache provide parallel sources of truth for latency.
    """

    __tablename__ = "kill_switch_events"
    __table_args__ = (
        CheckConstraint(
            f"trigger IN ('{KillSwitchTrigger.MANUAL}', '{KillSwitchTrigger.ENV_VAR}', "
            f"'{KillSwitchTrigger.DRAWDOWN}', '{KillSwitchTrigger.BUDGET_LLM}', "
            f"'{KillSwitchTrigger.BUDGET_TWITTERAPI}')",
            name="trigger_valid",
        ),
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    # True = activate, False = deactivate.
    activated: Mapped[bool] = mapped_column(Boolean, nullable=False)
    trigger: Mapped[str] = mapped_column(String(32), nullable=False)
    actor: Mapped[str] = mapped_column(String(128), nullable=False)
    reason: Mapped[str | None] = mapped_column(Text)
