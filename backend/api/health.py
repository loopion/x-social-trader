"""`/health`, `/ready`, `/metrics` endpoints (OBS-02 + OBS-03)."""

from __future__ import annotations

from typing import Annotated

from fastapi import APIRouter, Depends, Response
from fastapi.responses import JSONResponse
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

from backend.core.metrics import render
from backend.core.redis_client import ping_redis
from backend.core.settings import Settings, get_settings
from backend.db.session import get_session

router = APIRouter()

SessionDep = Annotated[AsyncSession, Depends(get_session)]
SettingsDep = Annotated[Settings, Depends(get_settings)]


@router.get("/health")
def health() -> dict[str, str]:
    """Liveness probe — process is alive, no dependency checks."""
    return {"status": "ok"}


@router.get("/ready")
async def ready(session: SessionDep, settings: SettingsDep) -> Response:
    """Readiness probe — returns 503 if any dependency is unreachable."""
    checks: dict[str, str] = {}

    try:
        await session.execute(text("SELECT 1"))
        checks["db"] = "ok"
    except Exception as exc:
        checks["db"] = f"fail: {type(exc).__name__}"

    checks["redis"] = "ok" if await ping_redis(settings.redis_url) else "fail"

    all_ok = all(v == "ok" for v in checks.values())
    return JSONResponse(content=checks, status_code=200 if all_ok else 503)


@router.get("/metrics")
def metrics() -> Response:
    """Prometheus scrape endpoint."""
    body, content_type = render()
    return Response(content=body, media_type=content_type)
