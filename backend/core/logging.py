"""structlog configuration + StructlogRedactor (OBS-01).

Every log record passes through `StructlogRedactor` **before** rendering so no
secret leaks to stdout or aggregated log sinks (INV-5). The redactor targets:

- Keys whose name contains a sensitive substring (``password``, ``token``, etc.).
- Values that match known secret patterns (``sk-…``, ``Bearer …``, ``ghp_…``).

Contextual ids — ``request_id``, ``event_id``, ``tweet_id``, ``order_id`` — are
attached via ``structlog.contextvars`` from middleware or worker code.
"""

from __future__ import annotations

import logging
import re
import sys
from collections.abc import MutableMapping
from typing import Any, cast

import structlog

REDACTED: str = "***REDACTED***"

SENSITIVE_KEY_SUBSTRINGS: frozenset[str] = frozenset(
    {
        "password",
        "passwd",
        "secret",
        "token",
        "api_key",
        "apikey",
        "authorization",
        "cookie",
        "bearer",
        "session_id",
        "twitterapi_io_key",
        "llm_api_key",
        "telegram_bot_token",
        "ib_account",
        "account_id",
        "ib_expected_account_id",
    }
)

SECRET_VALUE_PATTERNS: tuple[re.Pattern[str], ...] = (
    re.compile(r"sk-[A-Za-z0-9_\-]{10,}"),  # OpenAI-ish
    re.compile(r"xoxb-[A-Za-z0-9\-]+"),  # Slack
    re.compile(r"(?i)bearer\s+[A-Za-z0-9._\-]+"),
    re.compile(r"ghp_[A-Za-z0-9]{30,}"),  # GitHub PAT
    re.compile(r"AKIA[0-9A-Z]{16}"),  # AWS access key
)


def _key_is_sensitive(key: str) -> bool:
    k = key.lower()
    return any(s in k for s in SENSITIVE_KEY_SUBSTRINGS)


def _redact_string(value: str) -> str:
    redacted = value
    for pattern in SECRET_VALUE_PATTERNS:
        redacted = pattern.sub(REDACTED, redacted)
    return redacted


def _walk(obj: Any, parent_key: str = "") -> Any:
    if isinstance(obj, dict):
        return {k: _walk(v, parent_key=str(k)) for k, v in obj.items()}
    if isinstance(obj, list):
        return [_walk(item, parent_key=parent_key) for item in obj]
    if isinstance(obj, tuple):
        return tuple(_walk(item, parent_key=parent_key) for item in obj)
    if parent_key and _key_is_sensitive(parent_key):
        return REDACTED
    if isinstance(obj, str):
        return _redact_string(obj)
    return obj


class StructlogRedactor:
    """structlog processor — MUST run before the renderer."""

    def __call__(
        self,
        logger: object,
        method_name: str,
        event_dict: MutableMapping[str, Any],
    ) -> MutableMapping[str, Any]:
        return cast(MutableMapping[str, Any], _walk(dict(event_dict)))


def configure_logging(level: str = "INFO", json_logs: bool = True) -> None:
    """Idempotent structlog + stdlib logging setup."""
    log_level = logging.getLevelNamesMapping().get(level.upper(), logging.INFO)

    processors: list[structlog.typing.Processor] = [
        structlog.contextvars.merge_contextvars,
        structlog.processors.add_log_level,
        structlog.processors.TimeStamper(fmt="iso", utc=True),
        structlog.processors.StackInfoRenderer(),
        StructlogRedactor(),
    ]
    if json_logs:
        processors.append(structlog.processors.JSONRenderer())
    else:
        processors.append(structlog.dev.ConsoleRenderer(colors=True))

    structlog.configure(
        processors=processors,
        wrapper_class=structlog.make_filtering_bound_logger(log_level),
        logger_factory=structlog.PrintLoggerFactory(file=sys.stdout),
        cache_logger_on_first_use=True,
    )


def get_logger(name: str | None = None) -> structlog.stdlib.BoundLogger:
    return cast(structlog.stdlib.BoundLogger, structlog.get_logger(name))
