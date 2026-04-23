"""Async SQLAlchemy engine + session factory (DB-01).

Per CLAUDE.md §4: no `Base.metadata.create_all()` outside tests — schema is
managed exclusively by Alembic migrations (DB-03).
"""

from __future__ import annotations

from collections.abc import AsyncIterator
from typing import Any

from sqlalchemy.ext.asyncio import (
    AsyncEngine,
    AsyncSession,
    async_sessionmaker,
    create_async_engine,
)

from backend.core.settings import get_settings


def build_engine(database_url: str | None = None, **kwargs: Any) -> AsyncEngine:
    """Create a fresh async engine. Callers are responsible for disposing it.

    Kept as a factory (rather than a module-level singleton) so tests can
    build isolated engines pointing at temp databases.
    """
    url = database_url or get_settings().database_url
    return create_async_engine(url, future=True, **kwargs)


def build_session_factory(engine: AsyncEngine) -> async_sessionmaker[AsyncSession]:
    return async_sessionmaker(engine, class_=AsyncSession, expire_on_commit=False)


# -----------------------------------------------------------------------------
# Process-wide engine (used by the FastAPI api service).
# Tests must NOT import these — see tests/integration/conftest.py for isolation.
# -----------------------------------------------------------------------------
_engine: AsyncEngine | None = None
_session_factory: async_sessionmaker[AsyncSession] | None = None


def get_engine() -> AsyncEngine:
    global _engine
    if _engine is None:
        _engine = build_engine()
    return _engine


def get_session_factory() -> async_sessionmaker[AsyncSession]:
    global _session_factory
    if _session_factory is None:
        _session_factory = build_session_factory(get_engine())
    return _session_factory


async def get_session() -> AsyncIterator[AsyncSession]:
    """FastAPI dependency yielding an AsyncSession per request."""
    factory = get_session_factory()
    async with factory() as session:
        yield session


async def dispose_engine() -> None:
    """Tear down the process-wide engine — call on app shutdown."""
    global _engine, _session_factory
    if _engine is not None:
        await _engine.dispose()
    _engine = None
    _session_factory = None
