"""KillSwitchService + /kill-switch endpoints (KILL-01 + KILL-02 + KILL-03 + KILL-05)."""

from __future__ import annotations

from collections.abc import Iterator

import fakeredis.aioredis
import pytest
from fastapi.testclient import TestClient
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncEngine, AsyncSession

from backend.api.kill_switch import get_kill_switch_service
from backend.api.main import app
from backend.db.session import build_session_factory, get_session
from backend.kill_switch import KillSwitchService
from backend.kill_switch.service import trigger_from_drawdown
from backend.models import KillSwitchEvent
from backend.models.enums import KillSwitchTrigger

# --- KillSwitchService unit-ish tests (real DB, fake Redis) -----------------


@pytest.fixture
def fake_redis() -> fakeredis.aioredis.FakeRedis:
    """FakeRedis's async client has a sync constructor — regular fixture is fine."""
    return fakeredis.aioredis.FakeRedis()


async def test_is_active_defaults_to_inactive(
    session: AsyncSession, fake_redis: fakeredis.aioredis.FakeRedis
) -> None:
    service = KillSwitchService(session=session, redis_client=fake_redis, env_getter=lambda: None)
    state = await service.is_active()
    assert state.active is False
    assert state.source == "inactive"


async def test_env_var_overrides_everything(
    session: AsyncSession, fake_redis: fakeredis.aioredis.FakeRedis
) -> None:
    service = KillSwitchService(session=session, redis_client=fake_redis, env_getter=lambda: "1")
    state = await service.is_active()
    assert state.active is True
    assert state.source == "env"


async def test_activate_writes_audit_row_and_sets_redis(
    session: AsyncSession, fake_redis: fakeredis.aioredis.FakeRedis
) -> None:
    service = KillSwitchService(session=session, redis_client=fake_redis, env_getter=lambda: None)
    await service.activate(trigger=KillSwitchTrigger.MANUAL, actor="alice", reason="audit")
    await session.commit()

    rows = (await session.execute(select(KillSwitchEvent))).scalars().all()
    assert len(rows) == 1
    assert rows[0].activated is True
    assert rows[0].actor == "alice"

    state = await service.is_active()
    assert state.active is True
    assert state.source == "redis"


async def test_deactivate_clears_redis_and_appends_row(
    session: AsyncSession, fake_redis: fakeredis.aioredis.FakeRedis
) -> None:
    service = KillSwitchService(session=session, redis_client=fake_redis, env_getter=lambda: None)
    await service.activate(trigger=KillSwitchTrigger.MANUAL, actor="alice")
    await service.deactivate(actor="alice", reason="false alarm")
    await session.commit()

    rows = (await session.execute(select(KillSwitchEvent))).scalars().all()
    assert len(rows) == 2
    assert rows[-1].activated is False
    assert rows[-1].reason == "false alarm"

    state = await service.is_active()
    assert state.active is False


async def test_db_history_is_consulted_when_redis_is_empty(
    session: AsyncSession, fake_redis: fakeredis.aioredis.FakeRedis
) -> None:
    # Simulate a Redis outage: write the DB row directly and flush the cache.
    session.add(
        KillSwitchEvent(activated=True, trigger=KillSwitchTrigger.MANUAL.value, actor="preexisting")
    )
    await session.commit()

    service = KillSwitchService(session=session, redis_client=fake_redis, env_getter=lambda: None)
    state = await service.is_active()
    assert state.active is True
    assert state.source == "db"


async def test_trigger_from_drawdown_activates_when_breached(
    session: AsyncSession, fake_redis: fakeredis.aioredis.FakeRedis
) -> None:
    service = KillSwitchService(session=session, redis_client=fake_redis, env_getter=lambda: None)
    event = await trigger_from_drawdown(service, drawdown_pct=3.1, threshold_pct=3.0)
    assert event is not None
    assert event.trigger == KillSwitchTrigger.DRAWDOWN.value


async def test_trigger_from_drawdown_is_noop_under_threshold(
    session: AsyncSession, fake_redis: fakeredis.aioredis.FakeRedis
) -> None:
    service = KillSwitchService(session=session, redis_client=fake_redis, env_getter=lambda: None)
    event = await trigger_from_drawdown(service, drawdown_pct=1.5, threshold_pct=3.0)
    assert event is None


# --- HTTP endpoint tests (real DI overrides, fake Redis) --------------------


# Module-scope registry so override signatures can use Depends(get_session) —
# FastAPI doesn't resolve Depends(<closure>) reliably in nested fixture scopes.
_TEST_STATE: dict[str, object] = {}


async def _override_session() -> Iterator[AsyncSession]:  # type: ignore[misc]
    factory = _TEST_STATE["factory"]
    async with factory() as s:  # type: ignore[operator]
        yield s


from typing import Annotated  # noqa: E402

from fastapi import Depends  # noqa: E402


async def _override_service(
    session: Annotated[AsyncSession, Depends(get_session)],
) -> KillSwitchService:
    redis_client = _TEST_STATE["redis"]
    return KillSwitchService(
        session=session,
        redis_client=redis_client,  # type: ignore[arg-type]
        env_getter=lambda: None,
    )


@pytest.fixture
def api_client(
    engine: AsyncEngine,
    fake_redis: fakeredis.aioredis.FakeRedis,
) -> Iterator[TestClient]:
    """FastAPI TestClient wired to the migrated test DB + fake Redis."""
    _TEST_STATE["factory"] = build_session_factory(engine)
    _TEST_STATE["redis"] = fake_redis

    app.dependency_overrides[get_session] = _override_session
    app.dependency_overrides[get_kill_switch_service] = _override_service
    try:
        with TestClient(app) as client:
            yield client
    finally:
        app.dependency_overrides.clear()
        _TEST_STATE.clear()


def test_status_endpoint_returns_inactive_by_default(api_client: TestClient) -> None:
    response = api_client.get("/kill-switch")
    assert response.status_code == 200, response.text
    assert response.json() == {"active": False, "source": "inactive"}


def test_activate_via_endpoint_returns_active(api_client: TestClient) -> None:
    response = api_client.post("/kill-switch", headers={"X-Actor": "bob", "X-Reason": "panic"})
    assert response.status_code == 200
    body = response.json()
    assert body["active"] is True


def test_deactivate_requires_confirm_header(api_client: TestClient) -> None:
    api_client.post("/kill-switch", headers={"X-Actor": "bob"})
    response = api_client.post(
        "/kill-switch/deactivate",
        headers={"X-Actor": "bob", "X-Reason": "false alarm"},
    )
    assert response.status_code == 400
    assert "X-Confirm" in response.json()["detail"]


def test_deactivate_requires_reason(api_client: TestClient) -> None:
    api_client.post("/kill-switch", headers={"X-Actor": "bob"})
    response = api_client.post(
        "/kill-switch/deactivate",
        headers={"X-Actor": "bob", "X-Confirm": "I-understand"},
    )
    assert response.status_code == 400
    assert "X-Reason" in response.json()["detail"]


def test_deactivate_succeeds_with_headers(api_client: TestClient) -> None:
    api_client.post("/kill-switch", headers={"X-Actor": "bob"})
    response = api_client.post(
        "/kill-switch/deactivate",
        headers={
            "X-Actor": "bob",
            "X-Confirm": "I-understand",
            "X-Reason": "recovered from incident",
        },
    )
    assert response.status_code == 200
    assert response.json()["active"] is False
