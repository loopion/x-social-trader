from __future__ import annotations

from sqlalchemy import Float, Integer, String
from sqlalchemy.orm import Mapped, mapped_column

from backend.models.base import Base, TimestampMixin, UpdateTimestampMixin


class Position(Base, TimestampMixin, UpdateTimestampMixin):
    """Materialized position per symbol. Reconstructible from `fills` (EXEC-03).

    Mutable — this table is NOT protected by INV-4 triggers, it's a cached view.
    """

    __tablename__ = "positions"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    symbol: Mapped[str] = mapped_column(String(16), unique=True, nullable=False, index=True)
    quantity: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    avg_price_usd: Mapped[float] = mapped_column(Float, nullable=False, default=0.0)
    realized_pnl_usd: Mapped[float] = mapped_column(Float, nullable=False, default=0.0)
