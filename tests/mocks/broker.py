"""Mock `BrokerProvider` — records submissions and can emit fills on demand."""

from __future__ import annotations

import uuid
from datetime import UTC, datetime

from backend.providers import Fill, OrderReceipt, Position, ValidatedOrder


class MockBrokerProvider:
    """In-memory broker simulator.

    - ``connect`` / ``disconnect`` flip ``connected`` so readiness tests can
      assert lifecycle.
    - ``place_order`` records the order and returns a deterministic receipt
      (unless ``place_order_fails=True``).
    - ``cancel_all`` flips ``cancel_all_called`` so KILL-02 tests can assert.
    - ``simulate_fill`` synthesises a Fill against a previously placed order.
    - Read methods (``get_account_summary``, ``get_positions``,
      ``get_open_orders``) return whatever the test pre-seeded.
    """

    def __init__(
        self,
        *,
        place_order_fails: bool = False,
        account_summary: dict[str, float] | None = None,
        positions: list[Position] | None = None,
    ) -> None:
        self._fail = place_order_fails
        self._account_summary = dict(account_summary or {})
        self._positions = list(positions or [])
        self.connected = False
        self.placed: list[ValidatedOrder] = []
        self.receipts: list[OrderReceipt] = []
        self.fills: list[Fill] = []
        self.cancel_all_called = False

    # ---- Lifecycle ----------------------------------------------------------

    async def connect(self) -> None:
        self.connected = True

    async def disconnect(self) -> None:
        self.connected = False

    # ---- Write methods ------------------------------------------------------

    async def place_order(self, order: ValidatedOrder) -> OrderReceipt:
        if self._fail:
            raise RuntimeError("mock broker refused the order")
        receipt = OrderReceipt(
            idempotency_key=order.idempotency_key,
            external_id=f"EXT-{len(self.placed) + 1:06d}",
            submitted_at=datetime.now(UTC),
        )
        self.placed.append(order)
        self.receipts.append(receipt)
        return receipt

    async def cancel_all(self) -> None:
        self.cancel_all_called = True

    def simulate_fill(
        self,
        receipt: OrderReceipt,
        *,
        quantity: int,
        price: float,
        commission_usd: float = 0.0,
    ) -> Fill:
        fill = Fill(
            external_fill_id=f"FILL-{uuid.uuid4().hex[:12]}",
            order_external_id=receipt.external_id,
            symbol=self._lookup_symbol(receipt),
            quantity=quantity,
            price=price,
            commission_usd=commission_usd,
            filled_at=datetime.now(UTC),
        )
        self.fills.append(fill)
        return fill

    def _lookup_symbol(self, receipt: OrderReceipt) -> str:
        for order, r in zip(self.placed, self.receipts, strict=False):
            if r.idempotency_key == receipt.idempotency_key:
                return order.symbol
        raise LookupError(f"no placed order matching receipt {receipt.external_id}")

    # ---- Read methods -------------------------------------------------------

    async def get_account_summary(self) -> dict[str, float]:
        return dict(self._account_summary)

    async def get_positions(self) -> list[Position]:
        return list(self._positions)

    async def get_open_orders(self) -> list[OrderReceipt]:
        return list(self.receipts)
