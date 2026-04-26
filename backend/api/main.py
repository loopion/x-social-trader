from __future__ import annotations

from collections.abc import AsyncIterator
from contextlib import asynccontextmanager, suppress

from fastapi import FastAPI

from backend.api.admin_rules import router as admin_rules_router
from backend.api.health import router as health_router
from backend.api.kill_switch import router as kill_switch_router
from backend.api.middleware import MetricsMiddleware, RequestIDMiddleware
from backend.core.logging import configure_logging
from backend.core.settings import get_settings
from backend.db.session import dispose_engine
from backend.rules.loader import RuleLoadError
from backend.rules.store import RuleStore


@asynccontextmanager
async def lifespan(app: FastAPI) -> AsyncIterator[None]:
    configure_logging()
    settings = get_settings()
    store = RuleStore(settings.rules_dir)
    # Boot must not fail just because the rules dir is empty in dev —
    # operators reload via /admin/rules/reload once the YAML lands.
    with suppress(RuleLoadError):
        store.reload()
    app.state.rule_store = store
    try:
        yield
    finally:
        await dispose_engine()


app = FastAPI(title="x-social-trader", version="0.1.0", lifespan=lifespan)
app.add_middleware(MetricsMiddleware)
app.add_middleware(RequestIDMiddleware)
app.include_router(health_router)
app.include_router(kill_switch_router)
app.include_router(admin_rules_router)
