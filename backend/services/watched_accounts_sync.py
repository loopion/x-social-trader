"""Align twitterapi.io's monitor list with `watched_accounts` (ING-03)."""

from __future__ import annotations

from dataclasses import dataclass

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from backend.models.watched_account import WatchedAccount
from backend.providers import TwitterApiIoClient


@dataclass(frozen=True, slots=True)
class WatchedAccountsReport:
    added: tuple[str, ...]
    removed: tuple[str, ...]
    unchanged: tuple[str, ...]


async def sync_watched_accounts(
    client: TwitterApiIoClient,
    session: AsyncSession,
) -> WatchedAccountsReport:
    """Push adds/removes to twitterapi.io so its monitor list matches the DB.

    - DB rows with ``active=True`` not yet in the remote list → add.
    - Remote usernames not in the active DB set → remove.
    - Usernames present on both sides → unchanged.
    """
    result = await session.execute(
        select(WatchedAccount.username).where(WatchedAccount.active.is_(True))
    )
    db_active: set[str] = {row[0] for row in result.all()}

    remote = set(await client.list_monitored_users())

    to_add = sorted(db_active - remote)
    to_remove = sorted(remote - db_active)
    unchanged = sorted(db_active & remote)

    for username in to_add:
        await client.add_user_to_monitor(username)
    for username in to_remove:
        await client.remove_user_from_monitor(username)

    return WatchedAccountsReport(
        added=tuple(to_add),
        removed=tuple(to_remove),
        unchanged=tuple(unchanged),
    )
