"""Verify the 0001_initial migration produces the expected schema."""

from __future__ import annotations

from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncEngine

from backend.models import AUDIT_TABLES

EXPECTED_TABLES = {
    "alembic_version",
    "aliases",
    "events",
    "fills",
    "kill_switch_events",
    "llm_decisions",
    "orders",
    "positions",
    "raw_tweets",
    "risk_limits",
    "rule_evaluations",
    "settings",
    "watched_accounts",
}


async def _list_tables(engine: AsyncEngine) -> set[str]:
    async with engine.connect() as conn:
        result = await conn.execute(text("SELECT name FROM sqlite_master WHERE type='table'"))
        return {row[0] for row in result.all()}


async def _list_triggers(engine: AsyncEngine) -> set[str]:
    async with engine.connect() as conn:
        result = await conn.execute(text("SELECT name FROM sqlite_master WHERE type='trigger'"))
        return {row[0] for row in result.all()}


async def test_all_tables_created(engine: AsyncEngine) -> None:
    tables = await _list_tables(engine)
    assert EXPECTED_TABLES.issubset(tables), f"missing tables: {EXPECTED_TABLES - tables}"


async def test_append_only_triggers_exist_for_audit_tables(engine: AsyncEngine) -> None:
    """INV-4: every audit table must have both BEFORE UPDATE and BEFORE DELETE triggers."""
    triggers = await _list_triggers(engine)
    for table in AUDIT_TABLES:
        assert f"{table}_no_update" in triggers, f"missing UPDATE trigger on {table}"
        assert f"{table}_no_delete" in triggers, f"missing DELETE trigger on {table}"


async def test_alembic_version_recorded(engine: AsyncEngine) -> None:
    async with engine.connect() as conn:
        result = await conn.execute(text("SELECT version_num FROM alembic_version"))
        versions = [row[0] for row in result.all()]
    assert len(versions) == 1
