"""LLM daily spend tracker (LLM-03)."""

from __future__ import annotations

from datetime import UTC, datetime

import fakeredis.aioredis
import pytest
from sqlalchemy.ext.asyncio import AsyncSession

from backend.kill_switch import KillSwitchService
from backend.models.kill_switch_event import KillSwitchEvent
from backend.services.llm_budget import (
    LLMBudgetTracker,
    trigger_from_llm_budget,
)


@pytest.fixture
def fake_redis() -> fakeredis.aioredis.FakeRedis:
    return fakeredis.aioredis.FakeRedis()


def test_constructor_validates_limit(fake_redis: fakeredis.aioredis.FakeRedis) -> None:
    with pytest.raises(ValueError, match="limit_usd"):
        LLMBudgetTracker(redis_client=fake_redis, limit_usd=0)


async def test_record_call_aggregates_per_day(
    fake_redis: fakeredis.aioredis.FakeRedis,
) -> None:
    tracker = LLMBudgetTracker(redis_client=fake_redis, limit_usd=10.0)
    now = datetime(2026, 4, 24, 0, 0, tzinfo=UTC)
    s1 = await tracker.record_call(cost_usd=1.5, now=now)
    s2 = await tracker.record_call(cost_usd=2.0, now=now)
    assert s1.day == "2026-04-24"
    assert abs(s2.spend_usd - 3.5) < 1e-9
    assert not s2.over_budget


async def test_day_rollover_resets_counter(
    fake_redis: fakeredis.aioredis.FakeRedis,
) -> None:
    tracker = LLMBudgetTracker(redis_client=fake_redis, limit_usd=10.0)
    day1 = datetime(2026, 4, 24, 23, 59, tzinfo=UTC)
    day2 = datetime(2026, 4, 25, 0, 1, tzinfo=UTC)
    await tracker.record_call(cost_usd=4.0, now=day1)
    s = await tracker.record_call(cost_usd=1.0, now=day2)
    assert s.day == "2026-04-25"
    assert abs(s.spend_usd - 1.0) < 1e-9


async def test_over_budget_triggers_kill_switch(
    fake_redis: fakeredis.aioredis.FakeRedis, session: AsyncSession
) -> None:
    tracker = LLMBudgetTracker(redis_client=fake_redis, limit_usd=1.0)
    ks = KillSwitchService(session=session, redis_client=fake_redis, env_getter=lambda: None)
    status = await tracker.record_call(cost_usd=1.5, now=datetime(2026, 4, 24, tzinfo=UTC))
    assert status.over_budget

    activated = await trigger_from_llm_budget(ks, status=status)
    await session.commit()
    assert activated is True

    pre_active = await ks.is_active()
    assert pre_active.active is True
    assert pre_active.source == "redis"

    rows = (await session.execute(KillSwitchEvent.__table__.select())).all()
    assert any("LLM daily spend" in (r.reason or "") for r in rows)


async def test_under_budget_does_not_trigger(
    fake_redis: fakeredis.aioredis.FakeRedis, session: AsyncSession
) -> None:
    tracker = LLMBudgetTracker(redis_client=fake_redis, limit_usd=10.0)
    ks = KillSwitchService(session=session, redis_client=fake_redis, env_getter=lambda: None)
    status = await tracker.record_call(cost_usd=1.0)
    activated = await trigger_from_llm_budget(ks, status=status)
    assert activated is False
    assert (await ks.is_active()).active is False


async def test_negative_cost_is_rejected(
    fake_redis: fakeredis.aioredis.FakeRedis,
) -> None:
    tracker = LLMBudgetTracker(redis_client=fake_redis, limit_usd=10.0)
    with pytest.raises(ValueError, match="cost_usd"):
        await tracker.record_call(cost_usd=-0.01)


async def test_current_status_reads_without_incrementing(
    fake_redis: fakeredis.aioredis.FakeRedis,
) -> None:
    tracker = LLMBudgetTracker(redis_client=fake_redis, limit_usd=10.0)
    s = await tracker.current_status()
    assert s.spend_usd == 0.0
    s = await tracker.current_status()  # still 0
    assert s.spend_usd == 0.0
