"""Stub worker — real impl in EXEC-01 (phase 6). Keeps docker compose healthy.

WARNING: the real executor must never bypass risk_manager.validate() (INV-3)
and must respect the INV-1 double opt-in for live trading.
"""

from __future__ import annotations

import asyncio
import logging
import sys

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s %(levelname)s %(name)s %(message)s",
    stream=sys.stdout,
)
log = logging.getLogger("executor")


async def main() -> None:
    log.info("executor stub starting — real impl arrives in EXEC-01 (phase 6)")
    while True:
        await asyncio.sleep(60)
        log.info("executor heartbeat")


if __name__ == "__main__":
    asyncio.run(main())
