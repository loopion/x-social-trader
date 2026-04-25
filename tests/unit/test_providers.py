"""PROV-01 DTO validation + mock provider behaviour + protocol conformance."""

from __future__ import annotations

from datetime import UTC, datetime

import pytest
from pydantic import ValidationError

from backend.models.enums import Intent, OrderSide, OrderType, TimeHorizon, TradingMode
from backend.providers import (
    BrokerProvider,
    LLMDecision,
    LLMProvider,
    OrderReceipt,
    RawTweet,
    SocialFeedProvider,
    ValidatedOrder,
)
from tests.mocks import MockBrokerProvider, MockLLMProvider, MockSocialFeedProvider

# --- DTO validation ----------------------------------------------------------


def _raw_tweet(tid: str = "t1") -> RawTweet:
    return RawTweet(
        tweet_id=tid,
        x_user_id="u1",
        username="alice",
        content="hello",
        raw_json={},
        received_at=datetime.now(UTC),
    )


def test_raw_tweet_is_frozen() -> None:
    t = _raw_tweet()
    with pytest.raises(ValidationError):
        t.content = "mutated"


def test_llm_decision_rejects_confidence_out_of_range() -> None:
    with pytest.raises(ValidationError):
        LLMDecision(
            tickers=["TSLA"],
            intent=Intent.BULLISH,
            confidence=1.5,
            time_horizon=TimeHorizon.INTRADAY,
            reasoning="",
            model="m",
            prompt_version="v1",
        )


def test_validated_order_rejects_zero_quantity() -> None:
    with pytest.raises(ValidationError):
        ValidatedOrder(
            idempotency_key="k",
            event_id="e",
            strategy_id="s",
            trading_mode=TradingMode.PAPER,
            side=OrderSide.BUY,
            order_type=OrderType.MARKET,
            symbol="TSLA",
            quantity=0,
        )


def test_raw_tweet_forbids_extra_fields() -> None:
    with pytest.raises(ValidationError):
        RawTweet(
            tweet_id="t",
            x_user_id="u",
            username="n",
            content="c",
            raw_json={},
            received_at=datetime.now(UTC),
            unexpected="x",  # type: ignore[call-arg]
        )


# --- Mock behaviour ----------------------------------------------------------


async def test_mock_social_provider_yields_scripted_tweets() -> None:
    tweets = [_raw_tweet("t1"), _raw_tweet("t2"), _raw_tweet("t3")]
    provider = MockSocialFeedProvider(tweets=tweets)

    seen: list[str] = []
    async for t in provider.subscribe(["alice"]):
        seen.append(t.tweet_id)

    assert seen == ["t1", "t2", "t3"]
    assert provider.accounts_seen == [["alice"]]


async def test_mock_llm_provider_returns_scripted_response() -> None:
    scripted = LLMDecision(
        tickers=["TSLA"],
        intent=Intent.BULLISH,
        confidence=0.9,
        time_horizon=TimeHorizon.INTRADAY,
        reasoning="strong signal",
        model="mock",
        prompt_version="v1",
    )
    provider = MockLLMProvider(responses={"t1": scripted})

    result = await provider.analyze(_raw_tweet("t1"))
    assert result.decision == scripted
    assert len(provider.calls) == 1


async def test_mock_llm_provider_returns_noise_default_when_no_script() -> None:
    provider = MockLLMProvider()
    result = await provider.analyze(_raw_tweet("unknown"))
    assert result.decision.intent == Intent.NOISE
    assert result.decision.tickers == []


async def test_mock_broker_records_orders_and_returns_receipt() -> None:
    broker = MockBrokerProvider()
    order = ValidatedOrder(
        idempotency_key="k1",
        event_id="e1",
        strategy_id="s1",
        trading_mode=TradingMode.PAPER,
        side=OrderSide.BUY,
        order_type=OrderType.MARKET,
        symbol="TSLA",
        quantity=10,
    )
    receipt = await broker.place_order(order)
    assert isinstance(receipt, OrderReceipt)
    assert receipt.idempotency_key == "k1"
    assert broker.placed == [order]


async def test_mock_broker_place_order_fails_when_configured() -> None:
    broker = MockBrokerProvider(place_order_fails=True)
    order = ValidatedOrder(
        idempotency_key="k",
        event_id="e",
        strategy_id="s",
        trading_mode=TradingMode.PAPER,
        side=OrderSide.BUY,
        order_type=OrderType.MARKET,
        symbol="TSLA",
        quantity=1,
    )
    with pytest.raises(RuntimeError, match="refused"):
        await broker.place_order(order)


async def test_mock_broker_cancel_all_sets_flag() -> None:
    broker = MockBrokerProvider()
    await broker.cancel_all()
    assert broker.cancel_all_called is True


async def test_mock_broker_simulate_fill_produces_matching_fill() -> None:
    broker = MockBrokerProvider()
    order = ValidatedOrder(
        idempotency_key="k1",
        event_id="e1",
        strategy_id="s1",
        trading_mode=TradingMode.PAPER,
        side=OrderSide.BUY,
        order_type=OrderType.MARKET,
        symbol="TSLA",
        quantity=5,
    )
    receipt = await broker.place_order(order)
    fill = broker.simulate_fill(receipt, quantity=5, price=100.0)
    assert fill.symbol == "TSLA"
    assert fill.order_external_id == receipt.external_id
    assert broker.fills == [fill]


# --- Protocol conformance (static + runtime) ---------------------------------


def _takes_social(provider: SocialFeedProvider) -> SocialFeedProvider:
    return provider


def _takes_llm(provider: LLMProvider) -> LLMProvider:
    return provider


def _takes_broker(provider: BrokerProvider) -> BrokerProvider:
    return provider


def test_mocks_satisfy_provider_protocols() -> None:
    """If this imports and type-checks, the mocks fit the protocol shape."""
    _takes_social(MockSocialFeedProvider())
    _takes_llm(MockLLMProvider())
    _takes_broker(MockBrokerProvider())
