from __future__ import annotations

from sqlalchemy import CheckConstraint, Float, ForeignKey, Integer, String
from sqlalchemy.orm import Mapped, mapped_column

from backend.models.base import Base, TimestampMixin
from backend.models.enums import Intent, TimeHorizon


class Event(Base, TimestampMixin):
    """Enriched signal ready for rule engine. `event_id` is the idempotency key (INV-6)."""

    __tablename__ = "events"
    __table_args__ = (
        CheckConstraint(
            "intent IN ('"
            f"{Intent.BULLISH}', '{Intent.BEARISH}', '{Intent.NEUTRAL}', '{Intent.NOISE}')",
            name="intent_valid",
        ),
        CheckConstraint(
            "time_horizon IN ('"
            f"{TimeHorizon.INTRADAY}', '{TimeHorizon.SWING}', '{TimeHorizon.LONG}')",
            name="time_horizon_valid",
        ),
        CheckConstraint(
            "confidence >= 0.0 AND confidence <= 1.0",
            name="confidence_in_unit",
        ),
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    event_id: Mapped[str] = mapped_column(String(64), unique=True, nullable=False, index=True)
    raw_tweet_id: Mapped[int] = mapped_column(
        ForeignKey("raw_tweets.id", ondelete="RESTRICT"), nullable=False, index=True
    )
    llm_decision_id: Mapped[int] = mapped_column(
        ForeignKey("llm_decisions.id", ondelete="RESTRICT"), nullable=False, index=True
    )
    ticker: Mapped[str] = mapped_column(String(16), nullable=False, index=True)
    intent: Mapped[str] = mapped_column(String(16), nullable=False)
    confidence: Mapped[float] = mapped_column(Float, nullable=False)
    time_horizon: Mapped[str] = mapped_column(String(16), nullable=False)
