"""Market calendar abstraction (RISK-01).

Wraps `exchange_calendars` behind a narrow Protocol so:
- tests can stub without loading the real calendar,
- future phases can swap implementations (custom holiday overrides, etc.).

The MIC code is validated at startup against the library's known list.
"""

from __future__ import annotations

from datetime import datetime
from typing import Protocol

import exchange_calendars as ec


class MarketCalendar(Protocol):
    """Minimal surface the risk manager needs."""

    def is_open_at(self, ts: datetime) -> bool: ...


class ExchangeCalendarsAdapter:
    """Default impl backed by `exchange_calendars`.

    The caller must pass a timezone-aware datetime to ``is_open_at``. The
    underlying library handles holidays, early closes, and DST for ~60 markets.
    """

    def __init__(self, market_code: str) -> None:
        available = ec.get_calendar_names()
        if market_code not in available:
            raise ValueError(
                f"Unknown market code {market_code!r}; "
                f"see exchange_calendars.get_calendar_names() for the full list"
            )
        self._cal = ec.get_calendar(market_code)

    def is_open_at(self, ts: datetime) -> bool:
        if ts.tzinfo is None:
            raise ValueError("is_open_at requires a timezone-aware datetime")
        return bool(self._cal.is_open_on_minute(ts))
