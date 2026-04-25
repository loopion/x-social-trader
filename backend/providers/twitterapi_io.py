"""twitterapi.io adapter — HTTP client (ING-01) + WebSocket stream (ING-02).

Only this module may import the twitterapi.io SDK surface (httpx + websockets
pointed at twitterapi.io URLs); the rest of the codebase talks to the
`SocialFeedProvider` Protocol.

The exact REST endpoint paths below are best-effort placeholders — twitterapi.io's
routes are verified by invoice + curl, not inferred. Update the constants if
the first live call hits a 404; the client shape stays the same.
"""

from __future__ import annotations

import asyncio
import json
from collections.abc import AsyncIterator, Callable
from datetime import UTC, datetime
from types import TracebackType
from typing import Any, Self

import httpx
from websockets.asyncio.client import connect as default_ws_connect

from backend.core.logging import get_logger
from backend.core.metrics import tweets_ingested_total
from backend.providers.base import RawTweet

log = get_logger("providers.twitterapi_io")

# ---- Endpoint paths (TODO: verify against live API) -------------------------
PATH_ADD_USER = "/twitter/monitor/add_user"
PATH_REMOVE_USER = "/twitter/monitor/remove_user"
PATH_LIST_USERS = "/twitter/monitor/list"
PATH_ADVANCED_SEARCH = "/twitter/tweets/advanced_search"

# Retry policy for HTTP (only on 5xx or connection errors).
_HTTP_RETRY_MAX = 3
_HTTP_RETRY_BACKOFF_SECONDS = 1.0

# WebSocket reconnection backoff.
_WS_BACKOFF_INITIAL = 1.0
_WS_BACKOFF_MAX = 60.0


class TwitterApiIoError(RuntimeError):
    """Raised for non-retryable API errors (4xx, auth failures, etc.)."""


WsConnectFactory = Callable[[str], Any]


# -----------------------------------------------------------------------------
# HTTP client (ING-01)
# -----------------------------------------------------------------------------


class TwitterApiIoClient:
    """REST client. Use via ``async with`` for automatic connection teardown."""

    def __init__(
        self,
        *,
        api_key: str,
        base_url: str,
        timeout_seconds: float = 30.0,
        http_client: httpx.AsyncClient | None = None,
    ) -> None:
        if not api_key:
            raise TwitterApiIoError("TWITTERAPI_IO_KEY is required")
        self._api_key = api_key
        self._base_url = base_url.rstrip("/")
        self._http = http_client or httpx.AsyncClient(
            base_url=self._base_url,
            headers={"X-API-Key": api_key},
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

    # ---- Monitoring list --------------------------------------------------

    async def add_user_to_monitor(self, username: str) -> None:
        await self._post(PATH_ADD_USER, json={"username": username})

    async def remove_user_from_monitor(self, username: str) -> None:
        await self._post(PATH_REMOVE_USER, json={"username": username})

    async def list_monitored_users(self) -> list[str]:
        response = await self._get(PATH_LIST_USERS)
        body = response.json()
        users = body.get("users", [])
        return [u["username"] if isinstance(u, dict) else str(u) for u in users]

    # ---- Backfill ---------------------------------------------------------

    async def advanced_search(
        self,
        *,
        query: str,
        limit: int = 100,
    ) -> list[dict[str, Any]]:
        response = await self._get(
            PATH_ADVANCED_SEARCH,
            params={"query": query, "limit": limit},
        )
        data = response.json()
        items = data.get("tweets", data.get("data", []))
        return list(items)

    # ---- Internals --------------------------------------------------------

    async def _get(self, path: str, *, params: dict[str, Any] | None = None) -> httpx.Response:
        return await self._request("GET", path, params=params)

    async def _post(self, path: str, *, json: dict[str, Any] | None = None) -> httpx.Response:
        return await self._request("POST", path, json=json)

    async def _request(
        self,
        method: str,
        path: str,
        *,
        params: dict[str, Any] | None = None,
        json: dict[str, Any] | None = None,
    ) -> httpx.Response:
        last_exc: Exception | None = None
        for attempt in range(_HTTP_RETRY_MAX):
            try:
                response = await self._http.request(method, path, params=params, json=json)
            except httpx.RequestError as exc:
                last_exc = exc
                log.warning(
                    "twitterapi_io.http_request_error",
                    method=method,
                    path=path,
                    attempt=attempt + 1,
                    error=type(exc).__name__,
                )
            else:
                if 400 <= response.status_code < 500:
                    # 4xx are non-retryable — bubble up with body context.
                    raise TwitterApiIoError(
                        f"{method} {path} -> {response.status_code}: {response.text[:200]}"
                    )
                if response.status_code < 500:
                    return response
                last_exc = TwitterApiIoError(f"{method} {path} -> {response.status_code}")
                log.warning(
                    "twitterapi_io.http_5xx",
                    method=method,
                    path=path,
                    status=response.status_code,
                    attempt=attempt + 1,
                )
            await asyncio.sleep(_HTTP_RETRY_BACKOFF_SECONDS * (2**attempt))
        raise TwitterApiIoError(
            f"{method} {path} failed after {_HTTP_RETRY_MAX} attempts: {last_exc!r}"
        )


# -----------------------------------------------------------------------------
# WebSocket provider (ING-02)
# -----------------------------------------------------------------------------


def _parse_tweet(payload: dict[str, Any]) -> RawTweet:
    """Map twitterapi.io tweet event payload to our RawTweet DTO."""
    tweet = payload.get("tweet") or payload
    created_at = tweet.get("created_at") or tweet.get("time")
    if isinstance(created_at, str):
        received = datetime.fromisoformat(created_at.replace("Z", "+00:00"))
    elif isinstance(created_at, int | float):
        received = datetime.fromtimestamp(float(created_at), tz=UTC)
    else:
        received = datetime.now(UTC)

    return RawTweet(
        tweet_id=str(tweet["id"]),
        x_user_id=str(tweet.get("author_id") or tweet.get("user_id") or ""),
        username=str(tweet.get("username") or tweet.get("author_name") or ""),
        content=str(tweet.get("text") or tweet.get("content") or ""),
        lang=tweet.get("lang"),
        raw_json=payload,
        received_at=received,
    )


class TwitterApiIoProvider:
    """``SocialFeedProvider`` implementation. Handles reconnection internally."""

    def __init__(
        self,
        *,
        api_key: str,
        ws_url: str,
        ws_connect: WsConnectFactory = default_ws_connect,
    ) -> None:
        if not api_key:
            raise TwitterApiIoError("TWITTERAPI_IO_KEY is required")
        self._api_key = api_key
        self._ws_url = ws_url
        self._ws_connect = ws_connect
        self._running = True

    async def subscribe(self, accounts: list[str]) -> AsyncIterator[RawTweet]:
        """Yield tweets from the WebSocket stream until the task is cancelled.

        Assumes ``accounts`` are already registered with the monitoring list
        via ``TwitterApiIoClient.add_user_to_monitor`` (see services.watched_accounts_sync).
        """
        backoff = _WS_BACKOFF_INITIAL
        while self._running:
            try:
                async with self._ws_connect(self._ws_url) as ws:
                    backoff = _WS_BACKOFF_INITIAL
                    log.info("twitterapi_io.ws_connected", accounts=len(accounts))
                    async for message in ws:
                        payload = _decode(message)
                        event_type = payload.get("type") or payload.get("event")
                        if event_type == "connected":
                            continue
                        if event_type == "ping":
                            continue
                        if event_type == "tweet" or "tweet" in payload or "id" in payload:
                            raw = _parse_tweet(payload)
                            tweets_ingested_total.inc()
                            yield raw
            except Exception as exc:
                if not self._running:
                    return
                log.warning(
                    "twitterapi_io.ws_disconnect",
                    error=type(exc).__name__,
                    reconnect_in_seconds=backoff,
                )
                await asyncio.sleep(backoff)
                backoff = min(backoff * 2, _WS_BACKOFF_MAX)

    async def close(self) -> None:
        self._running = False


def _decode(message: object) -> dict[str, Any]:
    if isinstance(message, bytes):
        message = message.decode("utf-8")
    if isinstance(message, str):
        decoded = json.loads(message)
        if isinstance(decoded, dict):
            return decoded
    raise TwitterApiIoError(f"unexpected WS message payload: {type(message).__name__}")
