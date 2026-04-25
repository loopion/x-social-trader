"""KillSwitchService — activation, deactivation, and tri-source `is_active`."""

from __future__ import annotations

import os
from collections.abc import Awaitable, Callable
from dataclasses import dataclass
from typing import Any, cast

from redis.asyncio import Redis
from redis.asyncio import from_url as redis_from_url
from sqlalchemy import desc, select
from sqlalchemy.ext.asyncio import AsyncSession

from backend.core.metrics import kill_switch_activations_total
from backend.models.enums import KillSwitchTrigger
from backend.models.kill_switch_event import KillSwitchEvent

REDIS_KEY = "kill_switch:active"
REDIS_CHANNEL = "kill_switch"


@dataclass(frozen=True, slots=True)
class KillSwitchState:
    """Snapshot returned by `is_active` / status queries."""

    active: bool
    source: str  # env | redis | db | inactive


EnvGetter = Callable[[], str | None]


class KillSwitchService:
    """Coordinator for the three truth sources. Inject the session + redis
    client so tests can swap for fakes (see tests/unit/test_kill_switch.py).
    """

    def __init__(
        self,
        session: AsyncSession,
        redis_client: Redis,
        env_getter: EnvGetter = lambda: os.environ.get("KILL_SWITCH"),
    ) -> None:
        self._session = session
        self._redis = redis_client
        self._env_getter = env_getter

    # ---- Query --------------------------------------------------------------

    async def is_active(self) -> KillSwitchState:
        if (self._env_getter() or "").strip() in {"1", "true", "yes"}:
            return KillSwitchState(active=True, source="env")
        if await self._redis_flag():
            return KillSwitchState(active=True, source="redis")
        latest = await self._latest_db_event()
        if latest is not None and latest.activated:
            return KillSwitchState(active=True, source="db")
        return KillSwitchState(active=False, source="inactive")

    # ---- Mutations ----------------------------------------------------------

    async def activate(
        self,
        *,
        trigger: KillSwitchTrigger,
        actor: str,
        reason: str | None = None,
    ) -> KillSwitchEvent:
        event = KillSwitchEvent(
            activated=True,
            trigger=trigger.value,
            actor=actor,
            reason=reason,
        )
        self._session.add(event)
        await self._session.flush()
        await self._redis.set(REDIS_KEY, "1")
        await self._redis.publish(REDIS_CHANNEL, "activated")
        kill_switch_activations_total.labels(trigger=trigger.value).inc()
        return event

    async def deactivate(
        self,
        *,
        actor: str,
        reason: str,
    ) -> KillSwitchEvent:
        event = KillSwitchEvent(
            activated=False,
            trigger=KillSwitchTrigger.MANUAL.value,
            actor=actor,
            reason=reason,
        )
        self._session.add(event)
        await self._session.flush()
        await self._redis.delete(REDIS_KEY)
        await self._redis.publish(REDIS_CHANNEL, "deactivated")
        return event

    # ---- Internals ----------------------------------------------------------

    async def _redis_flag(self) -> bool:
        result = await cast("Awaitable[Any]", self._redis.get(REDIS_KEY))
        return result is not None

    async def _latest_db_event(self) -> KillSwitchEvent | None:
        stmt = select(KillSwitchEvent).order_by(desc(KillSwitchEvent.id)).limit(1)
        return (await self._session.execute(stmt)).scalar_one_or_none()


# -----------------------------------------------------------------------------
# Factory
# -----------------------------------------------------------------------------


def build_kill_switch_service(
    session: AsyncSession,
    redis_url: str,
) -> KillSwitchService:
    client = redis_from_url(redis_url)
    return KillSwitchService(session=session, redis_client=client)


# -----------------------------------------------------------------------------
# KILL-05 helper — called by executor's drawdown loop
# -----------------------------------------------------------------------------


async def trigger_from_drawdown(
    service: KillSwitchService,
    *,
    drawdown_pct: float,
    threshold_pct: float,
) -> KillSwitchEvent | None:
    """Activate the kill switch if ``drawdown_pct`` breached ``threshold_pct``.

    Returns the created event, or ``None`` if no action was taken. The
    executor loop is expected to call this periodically (EXEC-03 phase 6).
    """
    if drawdown_pct < threshold_pct:
        return None
    return await service.activate(
        trigger=KillSwitchTrigger.DRAWDOWN,
        actor="risk_manager",
        reason=(
            f"daily drawdown {drawdown_pct:.2f}% breached threshold {threshold_pct:.2f}% (KILL-05)"
        ),
    )
