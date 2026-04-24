from __future__ import annotations

from collections.abc import AsyncIterator
from contextlib import asynccontextmanager

from fastapi import FastAPI

from backend.api.health import router as health_router
from backend.api.kill_switch import router as kill_switch_router
from backend.api.middleware import MetricsMiddleware, RequestIDMiddleware
from backend.core.logging import configure_logging
from backend.db.session import dispose_engine


@asynccontextmanager
async def lifespan(app: FastAPI) -> AsyncIterator[None]:
    configure_logging()
    try:
        yield
    finally:
        await dispose_engine()


app = FastAPI(title="x-social-trader", version="0.1.0", lifespan=lifespan)
app.add_middleware(MetricsMiddleware)
app.add_middleware(RequestIDMiddleware)
app.include_router(health_router)
app.include_router(kill_switch_router)
