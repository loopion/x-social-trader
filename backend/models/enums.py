"""Enumerated value types used across multiple tables.

Stored as VARCHAR + CHECK constraint for cross-DB portability (SQLite in dev,
Postgres-ready later). Keep values lower-case and stable — they appear in
audit rows which are append-only (INV-4).
"""

from __future__ import annotations

from enum import StrEnum


class TradingMode(StrEnum):
    PAPER = "paper"
    LIVE = "live"


class Intent(StrEnum):
    BULLISH = "bullish"
    BEARISH = "bearish"
    NEUTRAL = "neutral"
    NOISE = "noise"


class TimeHorizon(StrEnum):
    INTRADAY = "intraday"
    SWING = "swing"
    LONG = "long"


class OrderSide(StrEnum):
    BUY = "buy"
    SELL = "sell"


class OrderType(StrEnum):
    """Market + limit only in phase 6; stop / options come later."""

    MARKET = "market"
    LIMIT = "limit"


class LLMDecisionStatus(StrEnum):
    SUCCESS = "success"
    INVALID_JSON = "invalid_json"
    ERROR = "error"


class RuleOutcome(StrEnum):
    MATCHED = "matched"
    SKIPPED = "skipped"
    FAILED = "failed"


class KillSwitchTrigger(StrEnum):
    MANUAL = "manual"
    ENV_VAR = "env_var"
    DRAWDOWN = "drawdown"
    BUDGET_LLM = "budget_llm"
    BUDGET_TWITTERAPI = "budget_twitterapi"
