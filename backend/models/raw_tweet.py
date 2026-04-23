from __future__ import annotations

from datetime import datetime

from sqlalchemy import JSON, DateTime, Integer, String, Text
from sqlalchemy.orm import Mapped, mapped_column

from backend.models.base import Base, TimestampMixin


class RawTweet(Base, TimestampMixin):
    """Durable raw capture from twitterapi.io before any LLM processing (ING-02).

    Not an audit table in the INV-4 sense (it may be refreshed with corrections
    from the provider if we discover a bug), but `tweet_id` UNIQUE enforces
    idempotence (INV-6).
    """

    __tablename__ = "raw_tweets"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    tweet_id: Mapped[str] = mapped_column(String(64), unique=True, nullable=False, index=True)
    x_user_id: Mapped[str] = mapped_column(String(32), nullable=False, index=True)
    username: Mapped[str] = mapped_column(String(64), nullable=False, index=True)
    content: Mapped[str] = mapped_column(Text, nullable=False)
    lang: Mapped[str | None] = mapped_column(String(8))
    raw_json: Mapped[dict] = mapped_column(JSON, nullable=False)  # type: ignore[type-arg]
    received_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, index=True
    )
