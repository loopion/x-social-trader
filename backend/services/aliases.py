"""Alias resolution — mention → ticker (LLM-04).

Looks up the ``aliases`` table to expand any free-text mentions the LLM
returned (e.g. ``"Tesla"`` → ``"TSLA"``, ``"$tsla"`` → ``"TSLA"``). The
LLM analyzer prompt instructs the model to keep ``tickers=[]`` when the
mapping is ambiguous, so this layer is the deterministic step that
attaches a ticker to a tweet.

Resolution rules:

* Mentions are matched **case-insensitively** and stripped of leading
  ``$`` (so ``$TSLA``, ``tsla``, and ``TSLA`` all map the same).
* Already-ticker-shaped mentions (uppercase A-Z, 1-5 chars, after
  ``$``-strip) are passed through if the row is missing — we trust the
  LLM picked a real ticker.
* When two alias rows share the same mention, the higher ``priority``
  wins; ties resolve to the lexicographically smaller ticker for
  determinism.
* Output is de-duplicated and sorted to keep ``event_id`` derivations
  stable across reruns (INV-6 idempotency).
"""

from __future__ import annotations

import re

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from backend.models.alias import Alias

_TICKER_RE = re.compile(r"^[A-Z]{1,5}$")


def _normalize(mention: str) -> str:
    return mention.lstrip("$").strip().lower()


def _looks_like_ticker(mention: str) -> bool:
    candidate = mention.lstrip("$").strip().upper()
    return bool(_TICKER_RE.fullmatch(candidate))


async def resolve_tickers(
    mentions: list[str],
    *,
    session: AsyncSession,
) -> list[str]:
    """Translate free-text mentions to a sorted, deduplicated ticker list.

    Empty input returns ``[]``. Unknown non-ticker-shaped mentions are
    silently dropped — they are noise, not events.
    """
    if not mentions:
        return []

    keys = {_normalize(m) for m in mentions if m and m.strip()}
    if not keys:
        return []

    rows = (
        await session.execute(
            select(Alias.mention, Alias.ticker, Alias.priority).where(
                func.lower(Alias.mention).in_(list(keys))
            )
        )
    ).all()

    # Group by lowercased mention, keep highest priority then lex-smallest.
    grouped: dict[str, tuple[int, str]] = {}
    for mention, ticker, priority in rows:
        key = _normalize(mention)
        existing = grouped.get(key)
        if existing is None or (priority, -ord(ticker[0]) if ticker else 0) > (
            existing[0],
            -ord(existing[1][0]) if existing[1] else 0,
        ):
            grouped[key] = (priority, ticker)

    resolved: set[str] = set()
    for raw in mentions:
        key = _normalize(raw)
        if key in grouped:
            resolved.add(grouped[key][1].upper())
        elif _looks_like_ticker(raw):
            resolved.add(raw.lstrip("$").strip().upper())
    return sorted(resolved)


__all__ = ["resolve_tickers"]
