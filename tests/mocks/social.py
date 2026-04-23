"""Mock `SocialFeedProvider` — scriptable iterator of RawTweet fixtures."""

from __future__ import annotations

import asyncio
from collections.abc import AsyncIterator, Iterable

from backend.providers import RawTweet


class MockSocialFeedProvider:
    """Yields the scripted tweets in order then exits the subscription.

    Call-site state (``accounts_seen``) lets tests assert which usernames were
    subscribed to. Pass ``delay`` to simulate a real streaming cadence.
    """

    def __init__(
        self,
        tweets: Iterable[RawTweet] | None = None,
        *,
        delay: float = 0.0,
    ) -> None:
        self._tweets: list[RawTweet] = list(tweets or [])
        self._delay = delay
        self.accounts_seen: list[list[str]] = []

    async def subscribe(self, accounts: list[str]) -> AsyncIterator[RawTweet]:
        self.accounts_seen.append(list(accounts))
        for tweet in self._tweets:
            if self._delay:
                await asyncio.sleep(self._delay)
            yield tweet
