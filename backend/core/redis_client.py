"""Redis ping helper for `/ready` (OBS-02).

Deliberately stateless: a fresh client is created for each probe so the
readiness check doesn't mask a dead connection pool. Real pub/sub + kill
switch distribution (KILL-01 / KILL-02) will live in their own module.
"""

from __future__ import annotations

import asyncio
from collections.abc import Awaitable
from typing import Any, cast

from redis.asyncio import from_url

PROBE_TIMEOUT_SECONDS: float = 2.0


async def ping_redis(url: str) -> bool:
    client = from_url(
        url,
        socket_timeout=PROBE_TIMEOUT_SECONDS,
        socket_connect_timeout=PROBE_TIMEOUT_SECONDS,
    )
    try:
        async with asyncio.timeout(PROBE_TIMEOUT_SECONDS):
            # redis-py's async Redis.ping overload is typed as Awaitable[bool] | bool;
            # under the async client it is always the Awaitable branch.
            result = await cast(Awaitable[Any], client.ping())
        return bool(result)
    except Exception:
        return False
    finally:
        await client.aclose()
