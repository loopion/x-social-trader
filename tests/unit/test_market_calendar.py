"""Thin smoke tests for the ExchangeCalendarsAdapter."""

from __future__ import annotations

from datetime import datetime

import pytest

from backend.risk.market_calendar import ExchangeCalendarsAdapter


def test_rejects_unknown_market_code() -> None:
    with pytest.raises(ValueError, match="Unknown market code"):
        ExchangeCalendarsAdapter("XXXX")


def test_accepts_known_market_codes() -> None:
    # Sanity: common choices are all present in exchange_calendars.
    for code in ("XNYS", "XPAR"):
        ExchangeCalendarsAdapter(code)


def test_requires_tz_aware_datetime() -> None:
    cal = ExchangeCalendarsAdapter("XNYS")
    with pytest.raises(ValueError, match="timezone-aware"):
        cal.is_open_at(datetime(2026, 4, 24, 14, 0))


def test_nyse_closed_on_a_weekend() -> None:
    """2026-04-25 is a Saturday — US markets closed."""
    from datetime import UTC  # local import so ruff keeps the per-test scope

    cal = ExchangeCalendarsAdapter("XNYS")
    assert not cal.is_open_at(datetime(2026, 4, 25, 14, 0, tzinfo=UTC))


def test_nyse_open_mid_session_on_weekday() -> None:
    """2026-04-24 14:30 UTC == 10:30 ET — well inside the regular session."""
    from datetime import UTC

    cal = ExchangeCalendarsAdapter("XNYS")
    assert cal.is_open_at(datetime(2026, 4, 24, 14, 30, tzinfo=UTC))
