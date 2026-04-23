"""Stub worker — real impl in TG-01 (phase 11). Keeps docker compose healthy."""

from __future__ import annotations

import asyncio
import logging
import sys

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s %(levelname)s %(name)s %(message)s",
    stream=sys.stdout,
)
log = logging.getLogger("telegram_bot")


async def main() -> None:
    log.info("telegram_bot stub starting — real impl arrives in TG-01 (phase 11)")
    while True:
        await asyncio.sleep(60)
        log.info("telegram_bot heartbeat")


if __name__ == "__main__":
    asyncio.run(main())
