"""OpenAICompatibleProvider — LLM-02 client tests (no real network)."""

from __future__ import annotations

import json
from datetime import UTC, datetime
from typing import Any

import httpx
import pytest

from backend.models.enums import Intent, LLMDecisionStatus, TimeHorizon
from backend.providers.base import RawTweet
from backend.providers.openai_compatible import (
    PROMPT_VERSION,
    OpenAICompatibleError,
    OpenAICompatibleProvider,
)


def _tweet() -> RawTweet:
    return RawTweet(
        tweet_id="t1",
        x_user_id="u1",
        username="alice",
        content="hello $TSLA gigafactory news",
        lang="en",
        raw_json={},
        received_at=datetime(2026, 4, 24, 14, 0, tzinfo=UTC),
    )


def _build_provider(handler: httpx.MockTransport) -> OpenAICompatibleProvider:
    http = httpx.AsyncClient(
        transport=handler,
        base_url="https://example.test/v1",
        headers={
            "Authorization": "Bearer test-key",  # pragma: allowlist secret
            "Content-Type": "application/json",
        },
    )
    return OpenAICompatibleProvider(
        api_key="test-key",  # pragma: allowlist secret
        base_url="https://example.test/v1",
        model="x-social-trader",
        cost_per_input_token_usd=0.000001,
        cost_per_output_token_usd=0.000002,
        http_client=http,
    )


def _ok_response(content_obj: dict[str, Any]) -> httpx.Response:
    return httpx.Response(
        200,
        json={
            "choices": [{"message": {"content": json.dumps(content_obj)}}],
            "usage": {"prompt_tokens": 1000, "completion_tokens": 50},
        },
    )


# --- Construction ---------------------------------------------------------


def test_provider_requires_api_key_base_url_and_model() -> None:
    with pytest.raises(OpenAICompatibleError, match="LLM_API_KEY"):
        OpenAICompatibleProvider(api_key="", base_url="https://x", model="m")
    with pytest.raises(OpenAICompatibleError, match="LLM_BASE_URL"):
        OpenAICompatibleProvider(api_key="k", base_url="", model="m")
    with pytest.raises(OpenAICompatibleError, match="LLM_MODEL"):
        OpenAICompatibleProvider(api_key="k", base_url="https://x", model="")


# --- Happy path -----------------------------------------------------------


async def test_analyze_parses_valid_json_response() -> None:
    payload = {
        "tickers": ["tsla"],
        "intent": "bullish",
        "confidence": 0.78,
        "time_horizon": "swing",
        "reasoning": "gigafactory boost",
    }

    def handler(_request: httpx.Request) -> httpx.Response:
        return _ok_response(payload)

    provider = _build_provider(httpx.MockTransport(handler))
    try:
        result = await provider.analyze(_tweet())
    finally:
        await provider.close()

    assert result.status is LLMDecisionStatus.SUCCESS
    assert result.decision.intent is Intent.BULLISH
    assert result.decision.tickers == ["TSLA"]  # uppercased
    assert result.decision.time_horizon is TimeHorizon.SWING
    assert result.decision.prompt_version == PROMPT_VERSION
    # cost = 1000 * 1e-6 + 50 * 2e-6 = 0.001 + 0.0001 = 0.0011
    assert abs(result.decision.cost_usd - 0.0011) < 1e-9
    assert "alice" in result.prompt


# --- Authorization header propagation ------------------------------------


async def test_authorization_header_is_set() -> None:
    seen: dict[str, str] = {}

    def handler(request: httpx.Request) -> httpx.Response:
        seen["auth"] = request.headers.get("authorization", "")
        return _ok_response(
            {
                "tickers": [],
                "intent": "noise",
                "confidence": 0.1,
                "time_horizon": "intraday",
                "reasoning": "n/a",
            }
        )

    provider = _build_provider(httpx.MockTransport(handler))
    try:
        await provider.analyze(_tweet())
    finally:
        await provider.close()

    assert seen["auth"] == "Bearer test-key"  # pragma: allowlist secret


# --- Invalid JSON retry path ---------------------------------------------


async def test_analyze_retries_once_on_invalid_json_then_succeeds() -> None:
    calls = {"n": 0}

    def handler(_request: httpx.Request) -> httpx.Response:
        calls["n"] += 1
        if calls["n"] == 1:
            return httpx.Response(
                200,
                json={
                    "choices": [{"message": {"content": "not-json-at-all"}}],
                    "usage": {"prompt_tokens": 100, "completion_tokens": 10},
                },
            )
        return _ok_response(
            {
                "tickers": ["AAPL"],
                "intent": "neutral",
                "confidence": 0.5,
                "time_horizon": "long",
                "reasoning": "ok",
            }
        )

    provider = _build_provider(httpx.MockTransport(handler))
    try:
        result = await provider.analyze(_tweet())
    finally:
        await provider.close()

    assert calls["n"] == 2  # exactly one retry
    assert result.status is LLMDecisionStatus.SUCCESS
    assert result.decision.tickers == ["AAPL"]


async def test_analyze_falls_back_to_noise_after_two_failures() -> None:
    def handler(_request: httpx.Request) -> httpx.Response:
        return httpx.Response(
            200,
            json={
                "choices": [{"message": {"content": "still nonsense"}}],
                "usage": {"prompt_tokens": 50, "completion_tokens": 5},
            },
        )

    provider = _build_provider(httpx.MockTransport(handler))
    try:
        result = await provider.analyze(_tweet())
    finally:
        await provider.close()

    assert result.status is LLMDecisionStatus.INVALID_JSON
    assert result.decision.intent is Intent.NOISE
    assert result.decision.tickers == []
    assert "still nonsense" in result.raw_response


# --- HTTP errors are surfaced --------------------------------------------


async def test_http_error_is_raised() -> None:
    def handler(_request: httpx.Request) -> httpx.Response:
        return httpx.Response(401, text="bad token")

    provider = _build_provider(httpx.MockTransport(handler))
    try:
        with pytest.raises(OpenAICompatibleError, match="HTTP 401"):
            await provider.analyze(_tweet())
    finally:
        await provider.close()
