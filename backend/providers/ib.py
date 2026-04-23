"""ib_insync adapter (IB-01 + IB-02).

Phase 5 is **read-only**: ``place_order`` and ``cancel_all`` raise until EXEC-01
(phase 6) wires them up behind the risk manager + kill switch. ``connect``
refuses to return if the managed account list does not contain
``IB_EXPECTED_ACCOUNT_ID`` (CLAUDE.md §5.4 — mismatch aborts startup).

The concrete ``ib_insync.IB`` instance is obtained through a factory so tests
can inject fakes without touching the real event loop.
"""

from __future__ import annotations

import asyncio
from collections.abc import Callable
from datetime import UTC, datetime
from typing import Any

import ib_insync

from backend.core.logging import get_logger
from backend.providers.base import (
    OrderReceipt,
    Position,
    ValidatedOrder,
)

log = get_logger("providers.ib")


class IBConnectionError(RuntimeError):
    """Refused to start — wrong account, mode mismatch, or gateway down."""


IBFactory = Callable[[], Any]


class IBProvider:
    """Broker provider backed by Interactive Brokers (ib_insync)."""

    def __init__(
        self,
        host: str,
        port: int,
        client_id: int,
        expected_account_id: str,
        *,
        connect_timeout: float = 10.0,
        retry_max: int = 3,
        retry_backoff: float = 1.0,
        ib_factory: IBFactory = ib_insync.IB,
    ) -> None:
        self._host = host
        self._port = port
        self._client_id = client_id
        self._expected_account_id = expected_account_id
        self._connect_timeout = connect_timeout
        self._retry_max = retry_max
        self._retry_backoff = retry_backoff
        self._ib_factory = ib_factory
        self._ib: Any | None = None

    # ---- Lifecycle ----------------------------------------------------------

    async def connect(self) -> None:
        """Connect + verify account. Raises IBConnectionError on mismatch."""
        ib = self._ib_factory()
        last_err: Exception | None = None
        for attempt in range(self._retry_max):
            try:
                async with asyncio.timeout(self._connect_timeout):
                    await ib.connectAsync(
                        host=self._host,
                        port=self._port,
                        clientId=self._client_id,
                    )
                break
            except Exception as exc:
                last_err = exc
                log.warning(
                    "ib.connect attempt failed",
                    attempt=attempt + 1,
                    error=type(exc).__name__,
                )
                await asyncio.sleep(self._retry_backoff * (2**attempt))
        else:
            raise IBConnectionError(
                f"connect failed after {self._retry_max} attempts: {last_err!r}"
            )

        managed = list(ib.managedAccounts() or [])
        if self._expected_account_id not in managed:
            ib.disconnect()
            raise IBConnectionError(
                f"expected account {self._expected_account_id!r} "
                f"not among managed accounts {managed!r}"
            )

        self._ib = ib
        log.info("ib.connect ok", account=self._expected_account_id)

    async def disconnect(self) -> None:
        if self._ib is not None and self._ib.isConnected():
            self._ib.disconnect()
        self._ib = None

    # ---- Read methods (IB-02) ----------------------------------------------

    async def get_account_summary(self) -> dict[str, float]:
        ib = self._require_connected()
        items = list(ib.accountSummary(self._expected_account_id) or [])
        result: dict[str, float] = {}
        for item in items:
            try:
                result[item.tag] = float(item.value)
            except (TypeError, ValueError):
                continue  # Non-numeric tags (Currency, …) are silently skipped.
        return result

    async def get_positions(self) -> list[Position]:
        ib = self._require_connected()
        raw = list(ib.positions(self._expected_account_id) or [])
        return [
            Position(
                symbol=p.contract.symbol,
                quantity=int(p.position),
                avg_price_usd=float(p.avgCost),
            )
            for p in raw
        ]

    async def get_open_orders(self) -> list[OrderReceipt]:
        ib = self._require_connected()
        raw = list(ib.openOrders() or [])
        now = datetime.now(UTC)
        return [
            OrderReceipt(
                idempotency_key=str(o.orderRef or o.orderId),
                external_id=str(o.orderId),
                submitted_at=now,
            )
            for o in raw
        ]

    # ---- Write methods (phase 6) ------------------------------------------

    async def place_order(self, order: ValidatedOrder) -> OrderReceipt:
        """Not yet exposed — EXEC-01 lands in phase 6.

        Keeping the method on the class satisfies the BrokerProvider Protocol
        while making misuse fail loudly instead of silently submitting.
        """
        raise NotImplementedError(
            "IBProvider.place_order is gated by EXEC-01 (phase 6). "
            "Until then the IB path is read-only (INV-1 safety)."
        )

    async def cancel_all(self) -> None:
        """Not yet exposed — KILL-02 lands in phase 6."""
        raise NotImplementedError("IBProvider.cancel_all is gated by KILL-02 (phase 6).")

    # ---- Internals ---------------------------------------------------------

    def _require_connected(self) -> Any:
        if self._ib is None or not self._ib.isConnected():
            raise IBConnectionError("IBProvider.connect() has not been called")
        return self._ib
