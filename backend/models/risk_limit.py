from __future__ import annotations

from sqlalchemy import Boolean, Float, Integer, String, UniqueConstraint
from sqlalchemy.orm import Mapped, mapped_column

from backend.models.base import Base, TimestampMixin, UpdateTimestampMixin


class RiskLimit(Base, TimestampMixin, UpdateTimestampMixin):
    """Per-strategy risk override. Versioned by `(strategy_id, version)`.

    Global limits live on `settings`; this table lets specific strategies run
    with tighter (or explicitly looser, with audit) caps. The risk manager
    picks the latest active version at order time.
    """

    __tablename__ = "risk_limits"
    __table_args__ = (
        UniqueConstraint("strategy_id", "version", name="uq_risk_limit_strategy_version"),
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    strategy_id: Mapped[str] = mapped_column(String(64), nullable=False, index=True)
    version: Mapped[int] = mapped_column(Integer, nullable=False, default=1)
    active: Mapped[bool] = mapped_column(Boolean, nullable=False, default=True)

    max_position_pct: Mapped[float | None] = mapped_column(Float)
    max_total_exposure_pct: Mapped[float | None] = mapped_column(Float)
    max_trades_per_day: Mapped[int | None] = mapped_column(Integer)
    max_daily_drawdown_pct: Mapped[float | None] = mapped_column(Float)
    allow_after_hours: Mapped[bool | None] = mapped_column(Boolean)
