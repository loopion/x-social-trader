from __future__ import annotations

from sqlalchemy import Integer, String, UniqueConstraint
from sqlalchemy.orm import Mapped, mapped_column

from backend.models.base import Base, TimestampMixin, UpdateTimestampMixin


class Alias(Base, TimestampMixin, UpdateTimestampMixin):
    """Map mentions (`Tesla`, `$TSLA`, `Elon's car company`) → ticker (`TSLA`)."""

    __tablename__ = "aliases"
    __table_args__ = (UniqueConstraint("mention", "ticker", name="uq_alias_mention_ticker"),)

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    mention: Mapped[str] = mapped_column(String(128), nullable=False, index=True)
    ticker: Mapped[str] = mapped_column(String(16), nullable=False, index=True)
    # Higher priority wins when the same mention maps to multiple tickers.
    priority: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
