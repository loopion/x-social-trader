"""Stub worker — real impl in LLM-02 (phase 8). Keeps docker compose healthy."""

from __future__ import annotations

import asyncio
import logging
import sys

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s %(levelname)s %(name)s %(message)s",
    stream=sys.stdout,
)
log = logging.getLogger("llm_worker")


async def main() -> None:
    log.info("llm_worker stub starting — real impl arrives in LLM-02 (phase 8)")
    while True:
        await asyncio.sleep(60)
        log.info("llm_worker heartbeat")


if __name__ == "__main__":
    asyncio.run(main())
