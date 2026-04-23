"""Stub worker — real impl in ING-01 (phase 7). Keeps docker compose healthy."""

from __future__ import annotations

import asyncio
import logging
import sys

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s %(levelname)s %(name)s %(message)s",
    stream=sys.stdout,
)
log = logging.getLogger("ingestion")


async def main() -> None:
    log.info("ingestion stub starting — real impl arrives in ING-01 (phase 7)")
    while True:
        await asyncio.sleep(60)
        log.info("ingestion heartbeat")


if __name__ == "__main__":
    asyncio.run(main())
