"""Provider protocol definitions + DTO models (PROV-01).

Business logic depends on these protocols, never on concrete implementations.
Concrete providers (``TwitterApiIoProvider``, ``OpenAICompatibleProvider``,
``IBProvider``) live alongside this module and are the only places where the
corresponding external SDKs may be imported (enforced by import-linter).

DTOs here are the **in-memory / wire** shape of the domain objects. They map
to — but are distinct from — the SQLAlchemy persistence models in
``backend.models``. Keep DTOs frozen and explicit (``extra="forbid"``).
"""

from __future__ import annotations

from collections.abc import AsyncIterator
from datetime import datetime
from typing import Any, Protocol

from pydantic import BaseModel, ConfigDict, Field

from backend.models.enums import (
    Intent,
    LLMDecisionStatus,
    OrderSide,
    OrderType,
    TimeHorizon,
    TradingMode,
)

# -----------------------------------------------------------------------------
# DTOs
# -----------------------------------------------------------------------------


class RawTweet(BaseModel):
    """Immutable capture of a tweet as it arrives from the social feed."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    tweet_id: str
    x_user_id: str
    username: str
    content: str
    lang: str | None = None
    raw_json: dict[str, Any]
    received_at: datetime


class LLMDecision(BaseModel):
    """Parsed + metadata-enriched LLM output — one per analysed tweet."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    tickers: list[str]
    intent: Intent
    confidence: float = Field(ge=0.0, le=1.0)
    time_horizon: TimeHorizon
    reasoning: str
    model: str
    prompt_version: str
    cost_usd: float = 0.0
    latency_ms: int = 0


class LLMAnalysisResult(BaseModel):
    """Provider return shape for ``analyze`` (LLM-02).

    Wraps the parsed ``LLMDecision`` with the audit fields the worker needs
    to satisfy INV-4 (``prompt`` + ``raw_response`` + ``status`` written to
    ``llm_decisions``). On parse failure ``decision.intent`` is ``noise``
    and ``status`` flags the failure mode for the audit row.
    """

    model_config = ConfigDict(frozen=True, extra="forbid")

    decision: LLMDecision
    prompt: str
    raw_response: str
    status: LLMDecisionStatus
    provider: str


class ValidatedOrder(BaseModel):
    """Order that has passed `risk_manager.validate()` (INV-3).

    Construction outside the risk manager is a bug — see RISK-01 for the
    hard enforcement (phase 6). Fields mirror `backend.models.order.Order`.
    """

    model_config = ConfigDict(frozen=True, extra="forbid")

    idempotency_key: str
    event_id: str
    strategy_id: str
    trading_mode: TradingMode
    side: OrderSide
    order_type: OrderType
    symbol: str
    quantity: int = Field(gt=0)
    limit_price: float | None = None


class OrderReceipt(BaseModel):
    """Broker acknowledgement returned from `place_order()`."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    idempotency_key: str
    external_id: str
    submitted_at: datetime


class Fill(BaseModel):
    """Broker-reported execution — one per partial or full fill."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    external_fill_id: str
    order_external_id: str
    symbol: str
    quantity: int = Field(gt=0)
    price: float = Field(gt=0.0)
    commission_usd: float = 0.0
    filled_at: datetime


class Position(BaseModel):
    """Broker-reported position snapshot. Shorts have ``quantity < 0``."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    symbol: str
    quantity: int
    avg_price_usd: float


# -----------------------------------------------------------------------------
# Protocols
# -----------------------------------------------------------------------------


class SocialFeedProvider(Protocol):
    """Streaming social feed (e.g. twitterapi.io WebSocket)."""

    def subscribe(self, accounts: list[str]) -> AsyncIterator[RawTweet]:
        """Yield tweets for the given account usernames until cancelled."""
        ...


class LLMProvider(Protocol):
    """LLM semantic analysis of a single tweet."""

    async def analyze(self, tweet: RawTweet) -> LLMAnalysisResult: ...


class BrokerProvider(Protocol):
    """Broker abstraction — place_order is gated by INV-1 and INV-3 upstream."""

    async def connect(self) -> None: ...

    async def disconnect(self) -> None: ...

    async def place_order(self, order: ValidatedOrder) -> OrderReceipt: ...

    async def cancel_all(self) -> None: ...

    # Read methods (IB-02, phase 5)
    async def get_account_summary(self) -> dict[str, float]: ...

    async def get_positions(self) -> list[Position]: ...

    async def get_open_orders(self) -> list[OrderReceipt]: ...
