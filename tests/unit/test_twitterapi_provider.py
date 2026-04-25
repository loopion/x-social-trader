"""TwitterApiIoProvider — ING-02 WebSocket stream tests (no real network)."""

from __future__ import annotations

import asyncio
import json
from typing import Any

import pytest

from backend.providers.twitterapi_io import TwitterApiIoProvider


class _FakeWs:
    """Minimal async-iterable WebSocket mock."""

    def __init__(self, messages: list[str], raise_after: int | None = None) -> None:
        self._messages = list(messages)
        self._raise_after = raise_after
        self._yielded = 0

    async def __aiter__(self):  # type: ignore[no-untyped-def]
        for msg in self._messages:
            self._yielded += 1
            if self._raise_after is not None and self._yielded > self._raise_after:
                raise ConnectionError("simulated disconnect")
            yield msg


class _FakeConnector:
    """Async context manager returning a _FakeWs. Tracks connect attempts."""

    def __init__(self, *scripts: list[str], post_loop_error: bool = False) -> None:
        self._scripts = list(scripts)
        self._post_loop_error = post_loop_error
        self.connect_calls = 0

    def __call__(self, _url: str) -> _FakeConnector:
        return self

    async def __aenter__(self) -> _FakeWs:
        self.connect_calls += 1
        if not self._scripts:
            raise ConnectionError("no more scripts")
        messages = self._scripts.pop(0)
        return _FakeWs(messages)

    async def __aexit__(self, *_: Any) -> None:
        pass


# --- Parsing ---------------------------------------------------------------


async def test_provider_yields_tweet_events_and_skips_pings() -> None:
    script = [
        json.dumps({"type": "connected"}),
        json.dumps({"type": "ping"}),
        json.dumps(
            {
                "type": "tweet",
                "tweet": {
                    "id": "42",
                    "author_id": "u1",
                    "username": "alice",
                    "text": "hello $TSLA",
                    "lang": "en",
                    "created_at": "2026-04-24T14:00:00Z",
                },
            }
        ),
    ]
    connector = _FakeConnector(script)
    provider = TwitterApiIoProvider(api_key="k", ws_url="wss://test", ws_connect=connector)

    received: list[str] = []

    async def consume() -> None:
        async for tweet in provider.subscribe(["alice"]):
            received.append(tweet.tweet_id)
            if len(received) == 1:
                await provider.close()
                return

    await asyncio.wait_for(consume(), timeout=2.0)
    assert received == ["42"]


async def test_provider_reconnects_on_disconnect(monkeypatch: pytest.MonkeyPatch) -> None:
    script1 = [json.dumps({"type": "tweet", "id": "1"})]
    script2 = [json.dumps({"type": "tweet", "id": "2"})]
    connector = _FakeConnector(script1, script2)
    provider = TwitterApiIoProvider(api_key="k", ws_url="wss://test", ws_connect=connector)

    received: list[str] = []

    async def consume() -> None:
        async for tweet in provider.subscribe(["alice"]):
            received.append(tweet.tweet_id)
            if len(received) == 2:
                await provider.close()
                return

    # Short-circuit the reconnect backoff sleep so the test stays fast.
    async def fast_sleep(_delay: float) -> None:
        return None

    monkeypatch.setattr("backend.providers.twitterapi_io.asyncio.sleep", fast_sleep)

    await asyncio.wait_for(consume(), timeout=2.0)

    assert received == ["1", "2"]
    assert connector.connect_calls == 2


# --- Safety ----------------------------------------------------------------


def test_provider_requires_api_key() -> None:
    with pytest.raises(Exception, match="required"):
        TwitterApiIoProvider(api_key="", ws_url="wss://test")
