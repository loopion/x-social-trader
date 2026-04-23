from __future__ import annotations

from sqlalchemy import JSON, CheckConstraint, Float, ForeignKey, Integer, String, Text
from sqlalchemy.orm import Mapped, mapped_column

from backend.models.base import Base, TimestampMixin
from backend.models.enums import LLMDecisionStatus


class LLMDecision(Base, TimestampMixin):
    """Audit row (INV-4) — append-only. Protected by triggers in migration 0001."""

    __tablename__ = "llm_decisions"
    __table_args__ = (
        CheckConstraint(
            "status IN ('"
            f"{LLMDecisionStatus.SUCCESS}', '"
            f"{LLMDecisionStatus.INVALID_JSON}', '"
            f"{LLMDecisionStatus.ERROR}')",
            name="status_valid",
        ),
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    raw_tweet_id: Mapped[int] = mapped_column(
        ForeignKey("raw_tweets.id", ondelete="RESTRICT"), nullable=False, index=True
    )
    prompt_version: Mapped[str] = mapped_column(String(32), nullable=False)
    model: Mapped[str] = mapped_column(String(128), nullable=False)
    provider: Mapped[str] = mapped_column(String(32), nullable=False)
    prompt: Mapped[str] = mapped_column(Text, nullable=False)
    raw_response: Mapped[str] = mapped_column(Text, nullable=False)
    parsed_decision: Mapped[dict | None] = mapped_column(JSON)  # type: ignore[type-arg]
    cost_usd: Mapped[float] = mapped_column(Float, nullable=False, default=0.0)
    latency_ms: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    status: Mapped[str] = mapped_column(
        String(16), nullable=False, default=LLMDecisionStatus.SUCCESS
    )
