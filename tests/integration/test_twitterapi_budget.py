"""TwitterApiBudgetTracker + trigger_from_budget integration tests."""

from __future__ import annotations

from datetime import UTC, datetime

import fakeredis.aioredis
import pytest
from sqlalchemy.ext.asyncio import AsyncSession

from backend.kill_switch import KillSwitchService
from backend.models.enums import KillSwitchTrigger
from backend.services.twitterapi_budget import (
    TwitterApiBudgetTracker,
    trigger_from_budget,
)


@pytest.fixture
def fake_redis() -> fakeredis.aioredis.FakeRedis:
    return fakeredis.aioredis.FakeRedis()


def test_tracker_rejects_invalid_config() -> None:
    r = fakeredis.aioredis.FakeRedis()
    with pytest.raises(ValueError):
        TwitterApiBudgetTracker(redis_client=r, cost_per_tweet_usd=-0.01, limit_usd=45.0)
    with pytest.raises(ValueError):
        TwitterApiBudgetTracker(redis_client=r, cost_per_tweet_usd=0.01, limit_usd=0.0)


async def test_record_tweet_increments_monthly_counter(
    fake_redis: fakeredis.aioredis.FakeRedis,
) -> None:
    tracker = TwitterApiBudgetTracker(
        redis_client=fake_redis, cost_per_tweet_usd=0.1, limit_usd=1.0
    )
    now = datetime(2026, 4, 24, 12, 0, tzinfo=UTC)

    s1 = await tracker.record_tweet(now=now)
    assert s1.month == "2026-04"
    assert s1.spend_usd == pytest.approx(0.1)
    assert not s1.over_budget

    s2 = await tracker.record_tweet(now=now)
    assert s2.spend_usd == pytest.approx(0.2)


async def test_over_budget_detection_at_threshold(
    fake_redis: fakeredis.aioredis.FakeRedis,
) -> None:
    tracker = TwitterApiBudgetTracker(
        redis_client=fake_redis, cost_per_tweet_usd=0.5, limit_usd=1.0
    )
    now = datetime(2026, 4, 24, 12, 0, tzinfo=UTC)

    s1 = await tracker.record_tweet(now=now)
    assert not s1.over_budget
    s2 = await tracker.record_tweet(now=now)
    # 1.0 >= 1.0 → over budget
    assert s2.over_budget


async def test_buckets_are_monthly(
    fake_redis: fakeredis.aioredis.FakeRedis,
) -> None:
    tracker = TwitterApiBudgetTracker(
        redis_client=fake_redis, cost_per_tweet_usd=1.0, limit_usd=100.0
    )
    april = datetime(2026, 4, 30, 23, 59, tzinfo=UTC)
    may = datetime(2026, 5, 1, 0, 0, tzinfo=UTC)

    await tracker.record_tweet(now=april)
    s_may = await tracker.record_tweet(now=may)
    assert s_may.month == "2026-05"
    assert s_may.spend_usd == pytest.approx(1.0)  # fresh bucket


async def test_trigger_from_budget_activates_kill_switch(
    session: AsyncSession, fake_redis: fakeredis.aioredis.FakeRedis
) -> None:
    tracker = TwitterApiBudgetTracker(
        redis_client=fake_redis, cost_per_tweet_usd=1.0, limit_usd=1.0
    )
    ks = KillSwitchService(session=session, redis_client=fake_redis, env_getter=lambda: None)

    status = await tracker.record_tweet()
    assert status.over_budget

    activated = await trigger_from_budget(ks, status=status)
    await session.commit()
    assert activated is True

    state = await ks.is_active()
    assert state.active is True
    # Audit row should carry the BUDGET_TWITTERAPI trigger.
    from sqlalchemy import select

    from backend.models import KillSwitchEvent

    rows = (await session.execute(select(KillSwitchEvent))).scalars().all()
    assert rows[-1].trigger == KillSwitchTrigger.BUDGET_TWITTERAPI.value


async def test_trigger_from_budget_noop_when_under(
    session: AsyncSession, fake_redis: fakeredis.aioredis.FakeRedis
) -> None:
    tracker = TwitterApiBudgetTracker(
        redis_client=fake_redis, cost_per_tweet_usd=0.1, limit_usd=100.0
    )
    ks = KillSwitchService(session=session, redis_client=fake_redis, env_getter=lambda: None)
    status = await tracker.record_tweet()
    assert not status.over_budget
    activated = await trigger_from_budget(ks, status=status)
    assert activated is False
