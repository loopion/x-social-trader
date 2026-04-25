"""OpenAI-compatible chat completions client + ``LLMProvider`` (LLM-02).

The actual SDK (``openai``, ``anthropic``) is forbidden outside this package
by import-linter. We talk to the chat-completions endpoint directly via
``httpx`` so a self-hosted gateway (e.g. the user's
``https://9router.pays.fr.eu.org/v1`` proxy) works the same way as
``api.openai.com``.

Behaviour:
* Loads the immutable analyzer prompt from ``prompts/analyzer_v1.md``.
* Forces JSON output with ``response_format={"type": "json_object"}`` (most
  OpenAI-compatible servers honour this; for those that don't the prompt
  also asks for raw JSON).
* On invalid JSON / schema mismatch: 1 retry with a corrective system
  message; if still invalid the result has ``intent=noise``,
  ``status=invalid_json`` and the raw text preserved for audit.
* Cost = ``prompt_tokens * cost_per_input + completion_tokens * cost_per_output``.
"""

from __future__ import annotations

import json
import time
from pathlib import Path
from types import TracebackType
from typing import Any, Self

import httpx
from pydantic import ValidationError

from backend.core.logging import get_logger
from backend.models.enums import Intent, LLMDecisionStatus, TimeHorizon
from backend.providers.base import LLMAnalysisResult, LLMDecision, RawTweet

log = get_logger("providers.openai_compatible")

PROMPT_VERSION = "v1"
PROMPT_PATH = Path(__file__).resolve().parents[2] / "prompts" / f"analyzer_{PROMPT_VERSION}.md"
PROVIDER_NAME = "openai_compatible"


class OpenAICompatibleError(RuntimeError):
    """Raised for non-retryable client errors (auth, 4xx, etc.)."""


def _load_system_prompt() -> str:
    text = PROMPT_PATH.read_text(encoding="utf-8")
    # Strip the human-only "Version identifier" preamble — the model sees the
    # System block onwards. Anything above ## System is metadata.
    marker = "## System"
    idx = text.find(marker)
    if idx == -1:
        raise OpenAICompatibleError(f"prompt file {PROMPT_PATH} missing '{marker}' header")
    return text[idx:].strip()


_SYSTEM_PROMPT = _load_system_prompt()

_RETRY_CORRECTION = (
    "Your previous response was not valid JSON or did not match the required "
    "schema. Respond again with ONLY a JSON object containing keys: tickers "
    "(list of uppercase strings), intent (one of bullish/bearish/neutral/"
    "noise), confidence (0.0-1.0), time_horizon (intraday/swing/long), "
    "reasoning (1-2 sentences). No markdown fences, no commentary."
)


def _user_message(tweet: RawTweet) -> str:
    return (
        f"Tweet from @{tweet.username} ({tweet.lang or 'unknown'}, "
        f"posted {tweet.received_at.isoformat()}):\n{tweet.content}"
    )


def _noise_decision(model: str, latency_ms: int, cost_usd: float) -> LLMDecision:
    return LLMDecision(
        tickers=[],
        intent=Intent.NOISE,
        confidence=0.0,
        time_horizon=TimeHorizon.INTRADAY,
        reasoning="LLM response could not be parsed as the required JSON schema.",
        model=model,
        prompt_version=PROMPT_VERSION,
        cost_usd=cost_usd,
        latency_ms=latency_ms,
    )


def _try_parse_decision(
    raw: str,
    *,
    model: str,
    cost_usd: float,
    latency_ms: int,
) -> LLMDecision | None:
    try:
        payload = json.loads(raw)
    except json.JSONDecodeError:
        return None
    if not isinstance(payload, dict):
        return None
    try:
        return LLMDecision(
            tickers=[str(t).upper() for t in payload.get("tickers", [])],
            intent=Intent(payload["intent"]),
            confidence=float(payload["confidence"]),
            time_horizon=TimeHorizon(payload["time_horizon"]),
            reasoning=str(payload.get("reasoning", "")),
            model=model,
            prompt_version=PROMPT_VERSION,
            cost_usd=cost_usd,
            latency_ms=latency_ms,
        )
    except (KeyError, ValueError, ValidationError):
        return None


class OpenAICompatibleProvider:
    """``LLMProvider`` implementation. Use as ``async with`` to share an HTTP pool."""

    def __init__(
        self,
        *,
        api_key: str,
        base_url: str,
        model: str,
        cost_per_input_token_usd: float = 0.0,
        cost_per_output_token_usd: float = 0.0,
        timeout_seconds: float = 30.0,
        http_client: httpx.AsyncClient | None = None,
    ) -> None:
        if not api_key:
            raise OpenAICompatibleError("LLM_API_KEY is required")
        if not base_url:
            raise OpenAICompatibleError("LLM_BASE_URL is required")
        if not model:
            raise OpenAICompatibleError("LLM_MODEL is required")
        self._model = model
        self._cost_in = cost_per_input_token_usd
        self._cost_out = cost_per_output_token_usd
        self._http = http_client or httpx.AsyncClient(
            base_url=base_url.rstrip("/"),
            headers={
                "Authorization": f"Bearer {api_key}",
                "Content-Type": "application/json",
            },
            timeout=httpx.Timeout(timeout_seconds, connect=10.0),
        )

    async def __aenter__(self) -> Self:
        return self

    async def __aexit__(
        self,
        exc_type: type[BaseException] | None,
        exc: BaseException | None,
        tb: TracebackType | None,
    ) -> None:
        await self.close()

    async def close(self) -> None:
        await self._http.aclose()

    # ---- Public API -------------------------------------------------------

    async def analyze(self, tweet: RawTweet) -> LLMAnalysisResult:
        """Run one analysis pass with at most one corrective retry."""
        user_msg = _user_message(tweet)
        messages: list[dict[str, str]] = [
            {"role": "system", "content": _SYSTEM_PROMPT},
            {"role": "user", "content": user_msg},
        ]

        first_raw, first_cost, first_latency = await self._call(messages)
        decision = _try_parse_decision(
            first_raw,
            model=self._model,
            cost_usd=first_cost,
            latency_ms=first_latency,
        )
        if decision is not None:
            return LLMAnalysisResult(
                decision=decision,
                prompt=user_msg,
                raw_response=first_raw,
                status=LLMDecisionStatus.SUCCESS,
                provider=PROVIDER_NAME,
            )

        # One retry with corrective hint.
        retry_messages = [
            *messages,
            {"role": "assistant", "content": first_raw},
            {"role": "system", "content": _RETRY_CORRECTION},
        ]
        retry_raw, retry_cost, retry_latency = await self._call(retry_messages)
        total_cost = first_cost + retry_cost
        total_latency = first_latency + retry_latency
        decision = _try_parse_decision(
            retry_raw,
            model=self._model,
            cost_usd=total_cost,
            latency_ms=total_latency,
        )
        if decision is not None:
            return LLMAnalysisResult(
                decision=decision,
                prompt=user_msg,
                raw_response=retry_raw,
                status=LLMDecisionStatus.SUCCESS,
                provider=PROVIDER_NAME,
            )

        log.warning(
            "openai_compatible.invalid_json_after_retry",
            tweet_id=tweet.tweet_id,
        )
        return LLMAnalysisResult(
            decision=_noise_decision(
                model=self._model,
                latency_ms=total_latency,
                cost_usd=total_cost,
            ),
            prompt=user_msg,
            raw_response=retry_raw,
            status=LLMDecisionStatus.INVALID_JSON,
            provider=PROVIDER_NAME,
        )

    # ---- Internals --------------------------------------------------------

    async def _call(self, messages: list[dict[str, str]]) -> tuple[str, float, int]:
        body: dict[str, Any] = {
            "model": self._model,
            "messages": messages,
            "response_format": {"type": "json_object"},
            "temperature": 0.1,
        }
        started = time.perf_counter()
        try:
            response = await self._http.post("/chat/completions", json=body)
        except httpx.RequestError as exc:
            raise OpenAICompatibleError(f"LLM request failed: {exc!r}") from exc
        latency_ms = int((time.perf_counter() - started) * 1000)
        if response.status_code >= 400:
            raise OpenAICompatibleError(f"LLM HTTP {response.status_code}: {response.text[:200]}")
        payload = response.json()
        choices = payload.get("choices") or []
        if not choices:
            raise OpenAICompatibleError("LLM returned no choices")
        content = choices[0].get("message", {}).get("content")
        if not isinstance(content, str):
            raise OpenAICompatibleError("LLM returned non-string content")

        usage = payload.get("usage") or {}
        prompt_tokens = int(usage.get("prompt_tokens", 0))
        completion_tokens = int(usage.get("completion_tokens", 0))
        cost = prompt_tokens * self._cost_in + completion_tokens * self._cost_out
        return content, cost, latency_ms
