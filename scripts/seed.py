"""DB-05 — idempotent seed.

Usage:
    uv run python scripts/seed.py

Creates:
- `settings` singleton row (id=1) with safe INV-1 defaults (paper mode).
- A handful of demo `watched_accounts`.
- Common ticker aliases.

Can be re-run freely — all inserts are INSERT OR IGNORE-style (no-op if row
with the same unique key already exists).
"""

from __future__ import annotations

import asyncio

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from backend.db.session import build_engine, build_session_factory
from backend.models import Alias, Settings, WatchedAccount

DEMO_ACCOUNTS: tuple[dict[str, object], ...] = (
    {"username": "elonmusk", "priority": 10, "active": True},
    {"username": "jeffbezos", "priority": 5, "active": True},
    {"username": "chamath", "priority": 3, "active": False},
)

DEMO_ALIASES: tuple[dict[str, object], ...] = (
    {"mention": "Tesla", "ticker": "TSLA", "priority": 10},
    {"mention": "$TSLA", "ticker": "TSLA", "priority": 20},
    {"mention": "Apple", "ticker": "AAPL", "priority": 10},
    {"mention": "$AAPL", "ticker": "AAPL", "priority": 20},
    {"mention": "Amazon", "ticker": "AMZN", "priority": 10},
)


async def seed_settings(session: AsyncSession) -> str:
    existing = await session.get(Settings, 1)
    if existing is not None:
        return "settings: exists (skipped)"
    session.add(Settings(id=1))  # type: ignore[call-arg]
    return "settings: created (paper mode, INV-1 defaults)"


async def seed_accounts(session: AsyncSession) -> str:
    created = 0
    for row in DEMO_ACCOUNTS:
        result = await session.execute(
            select(WatchedAccount).where(WatchedAccount.username == row["username"])
        )
        if result.scalar_one_or_none() is None:
            session.add(WatchedAccount(**row))  # type: ignore[arg-type]
            created += 1
    return f"watched_accounts: +{created}"


async def seed_aliases(session: AsyncSession) -> str:
    created = 0
    for row in DEMO_ALIASES:
        result = await session.execute(
            select(Alias).where(
                Alias.mention == row["mention"],
                Alias.ticker == row["ticker"],
            )
        )
        if result.scalar_one_or_none() is None:
            session.add(Alias(**row))  # type: ignore[arg-type]
            created += 1
    return f"aliases: +{created}"


async def main() -> None:
    engine = build_engine()
    factory = build_session_factory(engine)
    try:
        async with factory() as session:
            reports = [
                await seed_settings(session),
                await seed_accounts(session),
                await seed_aliases(session),
            ]
            await session.commit()
        for line in reports:
            print(line)
    finally:
        await engine.dispose()


if __name__ == "__main__":
    asyncio.run(main())
