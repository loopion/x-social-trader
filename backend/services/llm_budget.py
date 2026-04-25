"""LLM daily spend tracker (LLM-03).

Daily Redis ``INCRBYFLOAT`` counter keyed by ``llm_spend:YYYY-MM-DD`` (UTC).
Each successful (or attempted) LLM call increments the counter by the
calculated ``cost_usd``; once the daily sum exceeds ``LLM_MAX_USD_PER_DAY``
the kill switch trips with ``KillSwitchTrigger.BUDGET_LLM`` and the worker
must stop pulling new tweets.

Daily — not monthly — because the per-day cap is the line in CLAUDE.md §5.2
and a single bad day on a paid endpoint is more painful than a slow tweet
backlog.
"""

from __future__ import annotations

from collections.abc import Awaitable
from dataclasses import dataclass
from datetime import UTC, datetime
from typing import Any, cast

from redis.asyncio import Redis

from backend.kill_switch import KillSwitchService
from backend.models.enums import KillSwitchTrigger

REDIS_KEY_PREFIX = "llm_spend"


@dataclass(frozen=True, slots=True)
class LLMBudgetStatus:
    day: str  # YYYY-MM-DD
    spend_usd: float
    limit_usd: float

    @property
    def over_budget(self) -> bool:
        return self.spend_usd >= self.limit_usd

    @property
    def remaining_usd(self) -> float:
        return max(0.0, self.limit_usd - self.spend_usd)


def _day_key(now: datetime | None = None) -> str:
    ts = now or datetime.now(UTC)
    return f"{REDIS_KEY_PREFIX}:{ts.year:04d}-{ts.month:02d}-{ts.day:02d}"


class LLMBudgetTracker:
    """Records per-call USD spend against a daily Redis counter."""

    def __init__(
        self,
        *,
        redis_client: Redis,
        limit_usd: float,
    ) -> None:
        if limit_usd <= 0:
            raise ValueError("limit_usd must be > 0")
        self._redis = redis_client
        self._limit = limit_usd

    async def record_call(self, *, cost_usd: float, now: datetime | None = None) -> LLMBudgetStatus:
        if cost_usd < 0:
            raise ValueError("cost_usd must be ≥ 0")
        key = _day_key(now)
        raw = await cast("Awaitable[Any]", self._redis.incrbyfloat(key, cost_usd))
        spend = float(raw)
        return LLMBudgetStatus(day=key.split(":", 1)[1], spend_usd=spend, limit_usd=self._limit)

    async def current_status(self, *, now: datetime | None = None) -> LLMBudgetStatus:
        key = _day_key(now)
        raw = await cast("Awaitable[Any]", self._redis.get(key))
        spend = float(raw) if raw is not None else 0.0
        return LLMBudgetStatus(day=key.split(":", 1)[1], spend_usd=spend, limit_usd=self._limit)


async def trigger_from_llm_budget(
    kill_switch: KillSwitchService,
    *,
    status: LLMBudgetStatus,
) -> bool:
    """Activate the kill switch when the daily LLM budget is breached.

    Returns ``True`` iff the switch was activated. Mirrors
    ``trigger_from_budget`` in shape so audit rows explain exactly why.
    """
    if not status.over_budget:
        return False
    await kill_switch.activate(
        trigger=KillSwitchTrigger.BUDGET_LLM,
        actor="llm_budget_tracker",
        reason=(
            f"LLM daily spend {status.spend_usd:.4f} USD breached cap "
            f"{status.limit_usd:.2f} USD ({status.day})"
        ),
    )
    return True


__all__ = [
    "LLMBudgetStatus",
    "LLMBudgetTracker",
    "trigger_from_llm_budget",
]
