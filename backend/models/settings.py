"""`settings` table — runtime singleton row for trading mode + limits.

Distinct from `backend.core.settings.Settings` (env loader). The DB row is
the source of truth at runtime; env values bootstrap the initial row via seed.
Row is mutable (has `updated_at`) but there is ever exactly one row (`id=1`).
"""

from __future__ import annotations

from sqlalchemy import Boolean, CheckConstraint, Float, Integer, String
from sqlalchemy.orm import Mapped, mapped_column

from backend.models.base import Base, UpdateTimestampMixin
from backend.models.enums import TradingMode


class Settings(Base, UpdateTimestampMixin):
    __tablename__ = "settings"
    __table_args__ = (
        CheckConstraint("id = 1", name="singleton_row"),
        CheckConstraint(
            f"trading_mode IN ('{TradingMode.PAPER}', '{TradingMode.LIVE}')",
            name="trading_mode_valid",
        ),
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True, default=1)

    # INV-1 — double opt-in
    trading_mode: Mapped[str] = mapped_column(String(16), nullable=False, default=TradingMode.PAPER)
    paper_trading: Mapped[bool] = mapped_column(Boolean, nullable=False, default=True)

    # INV-3 — risk limits (can be overridden per strategy via `risk_limits`)
    max_capital_usd: Mapped[float] = mapped_column(Float, nullable=False, default=1000.0)
    max_position_pct: Mapped[float] = mapped_column(Float, nullable=False, default=2.0)
    max_total_exposure_pct: Mapped[float] = mapped_column(Float, nullable=False, default=20.0)
    max_trades_per_day: Mapped[int] = mapped_column(Integer, nullable=False, default=10)
    max_daily_drawdown_pct: Mapped[float] = mapped_column(Float, nullable=False, default=3.0)
    allow_after_hours: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)

    # Budgets
    llm_max_usd_per_day: Mapped[float] = mapped_column(Float, nullable=False, default=5.0)
    twitterapi_io_max_usd: Mapped[float] = mapped_column(Float, nullable=False, default=50.0)
