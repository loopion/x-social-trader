"""Watched accounts sync (ING-03) — DB ↔ twitterapi.io alignment."""

from __future__ import annotations

import httpx
from sqlalchemy.ext.asyncio import AsyncSession

from backend.models.watched_account import WatchedAccount
from backend.providers.twitterapi_io import TwitterApiIoClient
from backend.services.watched_accounts_sync import sync_watched_accounts


def _client_recording(
    remote_users: list[str],
    record: dict[str, list[str]],
) -> TwitterApiIoClient:
    record.setdefault("added", [])
    record.setdefault("removed", [])

    def handler(request: httpx.Request) -> httpx.Response:
        if request.url.path.endswith("/monitor/list"):
            return httpx.Response(200, json={"users": remote_users})
        if request.url.path.endswith("/monitor/add_user"):
            body = request.content.decode()
            record["added"].append(body)
            return httpx.Response(200, json={"ok": True})
        if request.url.path.endswith("/monitor/remove_user"):
            body = request.content.decode()
            record["removed"].append(body)
            return httpx.Response(200, json={"ok": True})
        return httpx.Response(404)

    http = httpx.AsyncClient(
        transport=httpx.MockTransport(handler),
        base_url="https://api.twitterapi.io",
        headers={"X-API-Key": "test-key"},
    )
    return TwitterApiIoClient(
        api_key="test-key",  # pragma: allowlist secret
        base_url="https://api.twitterapi.io",
        http_client=http,
    )


async def test_syncs_additions_and_deletions(session: AsyncSession) -> None:
    session.add(WatchedAccount(username="alice", active=True))
    session.add(WatchedAccount(username="bob", active=True))
    session.add(WatchedAccount(username="carol", active=False))  # not synced
    await session.commit()

    record: dict[str, list[str]] = {}
    client = _client_recording(remote_users=["bob", "dave"], record=record)
    report = await sync_watched_accounts(client, session)

    assert report.added == ("alice",)
    assert report.removed == ("dave",)
    assert report.unchanged == ("bob",)
    assert "alice" in record["added"][0]
    assert "dave" in record["removed"][0]


async def test_noop_when_lists_match(session: AsyncSession) -> None:
    session.add(WatchedAccount(username="alice", active=True))
    await session.commit()

    record: dict[str, list[str]] = {}
    client = _client_recording(remote_users=["alice"], record=record)
    report = await sync_watched_accounts(client, session)
    assert report.added == ()
    assert report.removed == ()
    assert report.unchanged == ("alice",)
