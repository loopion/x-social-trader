"""Mock `LLMProvider` — returns scripted decisions keyed by ``tweet_id``."""

from __future__ import annotations

from backend.models.enums import Intent, TimeHorizon
from backend.providers import LLMDecision, RawTweet

DEFAULT_NOISE = LLMDecision(
    tickers=[],
    intent=Intent.NOISE,
    confidence=0.0,
    time_horizon=TimeHorizon.INTRADAY,
    reasoning="no scripted response — mock default",
    model="mock",
    prompt_version="v0",
    cost_usd=0.0,
    latency_ms=0,
)


class MockLLMProvider:
    """`analyze(tweet)` returns ``responses[tweet.tweet_id]`` or DEFAULT_NOISE.

    ``calls`` records every tweet analysed for assertions.
    """

    def __init__(
        self,
        responses: dict[str, LLMDecision] | None = None,
        *,
        default: LLMDecision = DEFAULT_NOISE,
    ) -> None:
        self._responses = responses or {}
        self._default = default
        self.calls: list[RawTweet] = []

    async def analyze(self, tweet: RawTweet) -> LLMDecision:
        self.calls.append(tweet)
        return self._responses.get(tweet.tweet_id, self._default)
