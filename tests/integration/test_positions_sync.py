"""Integration test for `backend.services.positions_sync`.

Uses the real migrated SQLite via the shared integration `session` fixture
plus the MockBrokerProvider to avoid a real IB gateway.
"""

from __future__ import annotations

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from backend.models.position import Position as DBPosition
from backend.providers import Position
from backend.services.positions_sync import sync_positions
from tests.mocks import MockBrokerProvider


async def test_first_run_inserts_all_reported_positions(session: AsyncSession) -> None:
    broker = MockBrokerProvider(
        positions=[
            Position(symbol="TSLA", quantity=10, avg_price_usd=240.0),
            Position(symbol="AAPL", quantity=5, avg_price_usd=180.0),
        ]
    )
    report = await sync_positions(broker, session)
    await session.commit()

    assert (report.inserted, report.updated, report.cleared) == (2, 0, 0)

    rows = (await session.execute(select(DBPosition))).scalars().all()
    by_symbol = {r.symbol: r for r in rows}
    assert by_symbol["TSLA"].quantity == 10
    assert by_symbol["AAPL"].avg_price_usd == 180.0


async def test_changed_position_is_updated(session: AsyncSession) -> None:
    session.add(DBPosition(symbol="TSLA", quantity=10, avg_price_usd=240.0))
    await session.commit()

    broker = MockBrokerProvider(
        positions=[Position(symbol="TSLA", quantity=15, avg_price_usd=245.0)]
    )
    report = await sync_positions(broker, session)
    await session.commit()

    assert (report.inserted, report.updated, report.cleared) == (0, 1, 0)
    row = (
        await session.execute(select(DBPosition).where(DBPosition.symbol == "TSLA"))
    ).scalar_one()
    assert row.quantity == 15
    assert row.avg_price_usd == 245.0


async def test_symbol_dropped_by_broker_is_zeroed_not_deleted(session: AsyncSession) -> None:
    session.add(DBPosition(symbol="TSLA", quantity=10, avg_price_usd=240.0))
    session.add(DBPosition(symbol="AAPL", quantity=5, avg_price_usd=180.0))
    await session.commit()

    broker = MockBrokerProvider(
        positions=[Position(symbol="TSLA", quantity=10, avg_price_usd=240.0)]
    )
    report = await sync_positions(broker, session)
    await session.commit()

    assert (report.inserted, report.updated, report.cleared) == (0, 0, 1)
    aapl = (
        await session.execute(select(DBPosition).where(DBPosition.symbol == "AAPL"))
    ).scalar_one()
    assert aapl.quantity == 0


async def test_unchanged_positions_produce_no_writes(session: AsyncSession) -> None:
    session.add(DBPosition(symbol="TSLA", quantity=10, avg_price_usd=240.0))
    await session.commit()

    broker = MockBrokerProvider(
        positions=[Position(symbol="TSLA", quantity=10, avg_price_usd=240.0)]
    )
    report = await sync_positions(broker, session)
    await session.commit()
    assert (report.inserted, report.updated, report.cleared) == (0, 0, 0)
