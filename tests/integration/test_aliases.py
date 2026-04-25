"""Alias resolution (LLM-04) — DB-backed, integration-level."""

from __future__ import annotations

import pytest
from sqlalchemy.ext.asyncio import AsyncSession

from backend.models.alias import Alias
from backend.services.aliases import resolve_tickers


@pytest.fixture
async def aliased(session: AsyncSession) -> AsyncSession:
    session.add_all(
        [
            Alias(mention="Tesla", ticker="TSLA", priority=10),
            Alias(mention="tesla", ticker="TSLA", priority=10),
            Alias(mention="apple", ticker="AAPL", priority=10),
            # Lower-priority duplicate to verify priority wins.
            Alias(mention="apple", ticker="AAPL_LOW", priority=1),
        ]
    )
    await session.commit()
    return session


async def test_empty_input_returns_empty(session: AsyncSession) -> None:
    assert await resolve_tickers([], session=session) == []
    assert await resolve_tickers(["", "  "], session=session) == []


async def test_resolves_known_mention_case_insensitively(
    aliased: AsyncSession,
) -> None:
    out = await resolve_tickers(["Tesla", "TESLA", "tesla"], session=aliased)
    assert out == ["TSLA"]


async def test_strips_dollar_prefix_and_passes_through_ticker_shape(
    aliased: AsyncSession,
) -> None:
    # MSFT is not in aliases but matches the [A-Z]{1,5} ticker shape.
    out = await resolve_tickers(["$MSFT", "msft"], session=aliased)
    assert "MSFT" in out


async def test_priority_wins_over_lower_priority_duplicate(
    aliased: AsyncSession,
) -> None:
    out = await resolve_tickers(["Apple"], session=aliased)
    assert out == ["AAPL"]  # priority=10 row, not priority=1 (AAPL_LOW)


async def test_unknown_non_ticker_mention_is_dropped(aliased: AsyncSession) -> None:
    out = await resolve_tickers(["Elon's car company", ""], session=aliased)
    assert out == []


async def test_output_is_sorted_and_deduped(aliased: AsyncSession) -> None:
    out = await resolve_tickers(["Tesla", "tesla", "$TSLA", "Apple", "apple"], session=aliased)
    assert out == ["AAPL", "TSLA"]  # sorted, unique
