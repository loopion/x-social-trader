"""/ready unit tests — DB session + Redis ping are dependency-injected."""

from __future__ import annotations

from collections.abc import (
    AsyncIterator,
    Iterator,
)
from typing import Any
from unittest.mock import AsyncMock

import pytest
from fastapi.testclient import TestClient

from backend.api import health as health_module
from backend.api.main import app
from backend.db.session import get_session


class _FakeSession:
    """Minimal stand-in for AsyncSession — just supports the SELECT 1 probe."""

    def __init__(self, *, db_ok: bool) -> None:
        self._db_ok = db_ok

    async def execute(self, *_args: Any, **_kwargs: Any) -> Any:
        if not self._db_ok:
            raise RuntimeError("db down")
        return None


def _override_session(db_ok: bool) -> None:
    async def _provider() -> AsyncIterator[_FakeSession]:
        yield _FakeSession(db_ok=db_ok)

    app.dependency_overrides[get_session] = _provider


@pytest.fixture(autouse=True)
def reset_overrides() -> Iterator[None]:
    yield
    app.dependency_overrides.clear()


def test_ready_200_when_all_ok(client: TestClient, monkeypatch: pytest.MonkeyPatch) -> None:
    _override_session(db_ok=True)
    monkeypatch.setattr(health_module, "ping_redis", AsyncMock(return_value=True))
    response = client.get("/ready")
    assert response.status_code == 200
    assert response.json() == {"db": "ok", "redis": "ok"}


def test_ready_503_when_db_down(client: TestClient, monkeypatch: pytest.MonkeyPatch) -> None:
    _override_session(db_ok=False)
    monkeypatch.setattr(health_module, "ping_redis", AsyncMock(return_value=True))
    response = client.get("/ready")
    assert response.status_code == 503
    body = response.json()
    assert body["db"].startswith("fail")
    assert body["redis"] == "ok"


def test_ready_503_when_redis_down(client: TestClient, monkeypatch: pytest.MonkeyPatch) -> None:
    _override_session(db_ok=True)
    monkeypatch.setattr(health_module, "ping_redis", AsyncMock(return_value=False))
    response = client.get("/ready")
    assert response.status_code == 503
    assert response.json() == {"db": "ok", "redis": "fail"}
