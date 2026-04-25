"""Monthly twitterapi.io spend tracker (ING-03 budget guard).

Redis INCRBYFLOAT counter keyed by month (``twitterapi_spend:YYYY-MM``).
Each ingested tweet increments the counter by ``cost_per_tweet_usd``; once
the monthly sum exceeds the configured cap, `record_tweet` returns the new
spend and the caller must stop ingestion and trigger the kill switch.

Why monthly (not daily)?
- BACKLOG §5.1 explicitly calls the budget monthly.
- The user's $1.50/day target maps to ~$45/month.
- Rolling monthly is resistant to timezone edge cases that day-bucketed
  counters expose (one flipped hour can trim/extend a day by an hour).
"""

from __future__ import annotations

from collections.abc import Awaitable
from dataclasses import dataclass
from datetime import UTC, datetime
from typing import Any, cast

from redis.asyncio import Redis

from backend.kill_switch import KillSwitchService
from backend.kill_switch.service import trigger_from_drawdown  # re-used idiom
from backend.models.enums import KillSwitchTrigger

REDIS_KEY_PREFIX = "twitterapi_spend"


@dataclass(frozen=True, slots=True)
class BudgetStatus:
    month: str  # YYYY-MM
    spend_usd: float
    limit_usd: float

    @property
    def over_budget(self) -> bool:
        return self.spend_usd >= self.limit_usd

    @property
    def remaining_usd(self) -> float:
        return max(0.0, self.limit_usd - self.spend_usd)


def _month_key(now: datetime | None = None) -> str:
    ts = now or datetime.now(UTC)
    return f"{REDIS_KEY_PREFIX}:{ts.year:04d}-{ts.month:02d}"


class TwitterApiBudgetTracker:
    """Records per-tweet spend against a monthly Redis counter."""

    def __init__(
        self,
        *,
        redis_client: Redis,
        cost_per_tweet_usd: float,
        limit_usd: float,
    ) -> None:
        if cost_per_tweet_usd < 0:
            raise ValueError("cost_per_tweet_usd must be ≥ 0")
        if limit_usd <= 0:
            raise ValueError("limit_usd must be > 0")
        self._redis = redis_client
        self._cost = cost_per_tweet_usd
        self._limit = limit_usd

    async def record_tweet(self, *, now: datetime | None = None) -> BudgetStatus:
        key = _month_key(now)
        raw = await cast("Awaitable[Any]", self._redis.incrbyfloat(key, self._cost))
        spend = float(raw)
        month = key.split(":", 1)[1]
        return BudgetStatus(month=month, spend_usd=spend, limit_usd=self._limit)

    async def current_status(self, *, now: datetime | None = None) -> BudgetStatus:
        key = _month_key(now)
        raw = await cast("Awaitable[Any]", self._redis.get(key))
        spend = float(raw) if raw is not None else 0.0
        month = key.split(":", 1)[1]
        return BudgetStatus(month=month, spend_usd=spend, limit_usd=self._limit)


async def trigger_from_budget(
    kill_switch: KillSwitchService,
    *,
    status: BudgetStatus,
) -> bool:
    """Activate the kill switch when the monthly budget is breached.

    Returns True if the switch was activated, False otherwise. Uses a distinct
    ``KillSwitchTrigger.BUDGET_TWITTERAPI`` so audit rows explain exactly why.
    Parallels the KILL-05 helper `trigger_from_drawdown` in shape.
    """
    if not status.over_budget:
        return False
    await kill_switch.activate(
        trigger=KillSwitchTrigger.BUDGET_TWITTERAPI,
        actor="twitterapi_budget_tracker",
        reason=(
            f"twitterapi.io monthly spend {status.spend_usd:.4f} USD breached "
            f"cap {status.limit_usd:.2f} USD ({status.month})"
        ),
    )
    return True


# Expose trigger_from_drawdown at this package level so executor imports stay tidy.
__all__ = [
    "BudgetStatus",
    "TwitterApiBudgetTracker",
    "trigger_from_budget",
    "trigger_from_drawdown",
]
