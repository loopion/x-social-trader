"""Provider package — the only place allowed to import broker / social / LLM SDKs.

See `pyproject.toml` `[tool.importlinter]` for the enforced boundary (PROV-01).
"""

from backend.providers.base import (
    BrokerProvider,
    Fill,
    LLMAnalysisResult,
    LLMDecision,
    LLMProvider,
    OrderReceipt,
    Position,
    RawTweet,
    SocialFeedProvider,
    ValidatedOrder,
)
from backend.providers.openai_compatible import (
    PROMPT_VERSION as LLM_PROMPT_VERSION,
)
from backend.providers.openai_compatible import (
    OpenAICompatibleError,
    OpenAICompatibleProvider,
)
from backend.providers.twitterapi_io import (
    TwitterApiIoClient,
    TwitterApiIoError,
    TwitterApiIoProvider,
)

__all__ = [
    "LLM_PROMPT_VERSION",
    "BrokerProvider",
    "Fill",
    "LLMAnalysisResult",
    "LLMDecision",
    "LLMProvider",
    "OpenAICompatibleError",
    "OpenAICompatibleProvider",
    "OrderReceipt",
    "Position",
    "RawTweet",
    "SocialFeedProvider",
    "TwitterApiIoClient",
    "TwitterApiIoError",
    "TwitterApiIoProvider",
    "ValidatedOrder",
]
