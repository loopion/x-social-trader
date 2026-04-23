"""Sync broker-reported positions into the local ``positions`` table (IB-02).

Called periodically by the ``executor`` worker (phase 6 EXEC-03 wires the
scheduler). This module stays read-only relative to `fills` — positions are
a materialised view and can always be rebuilt from the fills audit log if
they diverge.
"""

from __future__ import annotations

from dataclasses import dataclass

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from backend.models.position import Position as DBPosition
from backend.providers import BrokerProvider, Position


@dataclass(frozen=True, slots=True)
class SyncReport:
    """Summary of the upsert. Useful for metrics + logs."""

    inserted: int
    updated: int
    cleared: int  # symbols that went to zero quantity


async def sync_positions(
    broker: BrokerProvider,
    session: AsyncSession,
) -> SyncReport:
    """Upsert every broker position into `positions`.

    Semantics:
    - Symbols reported by the broker are inserted or updated.
    - Local rows not reported by the broker are set to quantity=0 (``cleared``).
      We keep the row so the audit trail never loses a symbol we once held.
    """
    reported = await broker.get_positions()
    reported_by_symbol: dict[str, Position] = {p.symbol: p for p in reported}

    result = await session.execute(select(DBPosition))
    existing: dict[str, DBPosition] = {row.symbol: row for row in result.scalars()}

    inserted = updated = cleared = 0

    for symbol, snapshot in reported_by_symbol.items():
        row = existing.get(symbol)
        if row is None:
            session.add(
                DBPosition(
                    symbol=snapshot.symbol,
                    quantity=snapshot.quantity,
                    avg_price_usd=snapshot.avg_price_usd,
                )
            )
            inserted += 1
        elif row.quantity != snapshot.quantity or row.avg_price_usd != snapshot.avg_price_usd:
            row.quantity = snapshot.quantity
            row.avg_price_usd = snapshot.avg_price_usd
            updated += 1

    for symbol, row in existing.items():
        if symbol not in reported_by_symbol and row.quantity != 0:
            row.quantity = 0
            cleared += 1

    await session.flush()
    return SyncReport(inserted=inserted, updated=updated, cleared=cleared)
