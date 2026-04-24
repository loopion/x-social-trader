"""Build a `ValidationContext` from current DB + broker state.

This is a best-effort snapshot — the risk manager treats it as read-only.
Callers usually pull a fresh context per order.
"""

from __future__ import annotations

from datetime import UTC, datetime, timedelta

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from backend.models.order import Order
from backend.providers import BrokerProvider
from backend.risk import ValidationContext


class ValidationContextError(RuntimeError):
    """Raised when the context cannot be built (broker unreachable, etc.)."""


async def build_validation_context(
    *,
    broker: BrokerProvider,
    session: AsyncSession,
    now: datetime | None = None,
    daily_peak_usd: float | None = None,
    daily_pnl_usd: float = 0.0,
) -> ValidationContext:
    """Assemble the risk-manager inputs.

    The PnL / drawdown fields are plumbing for phase 10 backtest-derived
    numbers; callers pass in whatever they have (usually ``daily_peak_usd``
    equals current capital and ``daily_pnl_usd`` zero until fills accumulate).
    """
    now = now or datetime.now(UTC)

    summary = await broker.get_account_summary()
    capital = float(summary.get("NetLiquidation", 0.0))
    if capital <= 0.0:
        raise ValidationContextError(
            "broker.get_account_summary() returned no usable NetLiquidation; "
            "cannot build a ValidationContext"
        )

    positions = await broker.get_positions()
    total_exposure = float(sum(abs(p.quantity) * p.avg_price_usd for p in positions))

    midnight_utc = datetime(now.year, now.month, now.day, tzinfo=UTC)
    next_midnight = midnight_utc + timedelta(days=1)

    trades_today = int(
        (
            await session.execute(
                select(func.count())
                .select_from(Order)
                .where(
                    Order.created_at >= midnight_utc,
                    Order.created_at < next_midnight,
                )
            )
        ).scalar_one()
    )

    existing_events = {
        row[0] for row in (await session.execute(select(Order.event_id).distinct())).all()
    }
    existing_keys = {
        row[0] for row in (await session.execute(select(Order.idempotency_key).distinct())).all()
    }

    return ValidationContext(
        now=now,
        account_capital_usd=capital,
        total_exposure_usd=total_exposure,
        trades_today=trades_today,
        daily_pnl_usd=daily_pnl_usd,
        daily_peak_usd=daily_peak_usd if daily_peak_usd is not None else capital,
        seen_event_ids=frozenset(existing_events),
        seen_idempotency_keys=frozenset(existing_keys),
    )
