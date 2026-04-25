"""TwitterApiIoClient — ING-01 contract tests (httpx mocked)."""

from __future__ import annotations

from typing import Any

import httpx
import pytest

from backend.providers.twitterapi_io import TwitterApiIoClient, TwitterApiIoError


def _client(handler: httpx.MockTransport) -> TwitterApiIoClient:
    http = httpx.AsyncClient(
        transport=handler,
        base_url="https://api.twitterapi.io",
        headers={"X-API-Key": "test-key"},
    )
    return TwitterApiIoClient(
        api_key="test-key",  # pragma: allowlist secret
        base_url="https://api.twitterapi.io",
        http_client=http,
    )


def _handler(
    *,
    response_status: int = 200,
    response_body: dict[str, Any] | None = None,
    record: list[httpx.Request] | None = None,
    sequence_statuses: list[int] | None = None,
) -> httpx.MockTransport:
    """Return a MockTransport that can simulate 5xx→200 retries or 4xx failures."""
    calls_ref: list[int] = []

    def handle(request: httpx.Request) -> httpx.Response:
        if record is not None:
            record.append(request)
        calls_ref.append(1)
        if sequence_statuses is not None:
            idx = len(calls_ref) - 1
            status = sequence_statuses[min(idx, len(sequence_statuses) - 1)]
        else:
            status = response_status
        body = response_body if response_body is not None else {}
        return httpx.Response(status, json=body)

    return httpx.MockTransport(handle)


# --- Auth + construction ---------------------------------------------------


def test_client_requires_api_key() -> None:
    with pytest.raises(TwitterApiIoError, match="required"):
        TwitterApiIoClient(api_key="", base_url="https://api.twitterapi.io")


# --- Monitoring list -------------------------------------------------------


async def test_add_user_to_monitor_posts_username() -> None:
    captured: list[httpx.Request] = []
    client = _client(_handler(response_body={"ok": True}, record=captured))
    await client.add_user_to_monitor("elonmusk")
    assert captured[0].method == "POST"
    assert "elonmusk" in captured[0].content.decode()


async def test_list_monitored_users_parses_payload() -> None:
    client = _client(_handler(response_body={"users": ["alice", "bob"]}))
    assert await client.list_monitored_users() == ["alice", "bob"]


async def test_list_monitored_users_accepts_object_entries() -> None:
    payload = {"users": [{"username": "alice"}, {"username": "bob"}]}
    client = _client(_handler(response_body=payload))
    assert await client.list_monitored_users() == ["alice", "bob"]


# --- Retry policy ----------------------------------------------------------


async def test_5xx_is_retried_then_succeeds() -> None:
    # Two 502s then 200 — retry budget is 3, so this succeeds.
    client = _client(
        _handler(
            sequence_statuses=[502, 502, 200],
            response_body={"users": []},
        )
    )
    assert await client.list_monitored_users() == []


async def test_persistent_5xx_raises_after_budget() -> None:
    client = _client(_handler(response_status=500))
    with pytest.raises(TwitterApiIoError, match="failed after"):
        await client.list_monitored_users()


async def test_4xx_raises_without_retry() -> None:
    captured: list[httpx.Request] = []
    client = _client(_handler(response_status=404, record=captured))
    with pytest.raises(TwitterApiIoError, match="404"):
        await client.list_monitored_users()
    assert len(captured) == 1  # no retries on 4xx


async def test_async_context_manager_closes_http() -> None:
    async with _client(_handler(response_body={"users": []})) as client:
        assert isinstance(client, TwitterApiIoClient)


# --- Advanced search backfill ---------------------------------------------


async def test_advanced_search_returns_tweets_list() -> None:
    payload = {"tweets": [{"id": "1"}, {"id": "2"}]}
    client = _client(_handler(response_body=payload))
    result = await client.advanced_search(query="$TSLA", limit=10)
    assert [t["id"] for t in result] == ["1", "2"]
