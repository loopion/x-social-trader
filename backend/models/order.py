from __future__ import annotations

from sqlalchemy import CheckConstraint, Float, ForeignKey, Integer, String
from sqlalchemy.orm import Mapped, mapped_column

from backend.models.base import Base, TimestampMixin
from backend.models.enums import OrderSide, OrderType, TradingMode


class Order(Base, TimestampMixin):
    """Immutable submission record (INV-4 append-only).

    Subsequent state (ACK from broker, fills, cancellations) is tracked by
    separate audit logs (`fills` + future `order_status_events`). `orders`
    stays pristine as the submission snapshot.

    `idempotency_key = hash(event_id + strategy_id)` enforces INV-6.
    """

    __tablename__ = "orders"
    __table_args__ = (
        CheckConstraint(f"side IN ('{OrderSide.BUY}', '{OrderSide.SELL}')", name="side_valid"),
        CheckConstraint(
            f"order_type IN ('{OrderType.MARKET}', '{OrderType.LIMIT}')",
            name="order_type_valid",
        ),
        CheckConstraint(
            f"trading_mode IN ('{TradingMode.PAPER}', '{TradingMode.LIVE}')",
            name="trading_mode_valid",
        ),
        CheckConstraint("quantity > 0", name="quantity_positive"),
        CheckConstraint(
            f"(order_type = '{OrderType.LIMIT}' AND limit_price IS NOT NULL)"
            f" OR (order_type = '{OrderType.MARKET}' AND limit_price IS NULL)",
            name="limit_price_required_for_limit",
        ),
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    idempotency_key: Mapped[str] = mapped_column(
        String(128), unique=True, nullable=False, index=True
    )
    event_id: Mapped[str] = mapped_column(
        ForeignKey("events.event_id", ondelete="RESTRICT"), nullable=False, index=True
    )
    strategy_id: Mapped[str] = mapped_column(String(64), nullable=False)
    # Broker-assigned id, set during submission callback (non-null in practice).
    external_id: Mapped[str | None] = mapped_column(String(64), index=True)
    trading_mode: Mapped[str] = mapped_column(String(16), nullable=False)
    side: Mapped[str] = mapped_column(String(8), nullable=False)
    order_type: Mapped[str] = mapped_column(String(16), nullable=False)
    symbol: Mapped[str] = mapped_column(String(16), nullable=False, index=True)
    quantity: Mapped[int] = mapped_column(Integer, nullable=False)
    limit_price: Mapped[float | None] = mapped_column(Float)
