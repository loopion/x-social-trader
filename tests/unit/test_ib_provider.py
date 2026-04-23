"""IBProvider — covers IB-01 (connect + account verify) and IB-02 (reads).

ib_insync.IB is substituted via the provider's `ib_factory` kwarg so tests
never touch a real event loop or gateway.
"""

from __future__ import annotations

from types import SimpleNamespace
from typing import Any

import pytest

from backend.models.enums import OrderSide, OrderType, TradingMode
from backend.providers import Position, ValidatedOrder
from backend.providers.base import BrokerProvider
from backend.providers.ib import IBConnectionError, IBProvider


class _FakeIB:
    """Minimal drop-in for ``ib_insync.IB`` sufficient for phase-5 tests."""

    def __init__(
        self,
        *,
        managed_accounts: list[str] | None = None,
        account_summary: list[Any] | None = None,
        positions: list[Any] | None = None,
        open_orders: list[Any] | None = None,
        connect_raises: BaseException | None = None,
    ) -> None:
        self._managed = list(managed_accounts or [])
        self._summary = list(account_summary or [])
        self._positions = list(positions or [])
        self._open_orders = list(open_orders or [])
        self._connect_raises = connect_raises
        self._connected = False
        self.connect_calls = 0
        self.disconnect_calls = 0

    async def connectAsync(self, *, host: str, port: int, clientId: int) -> None:
        self.connect_calls += 1
        if self._connect_raises is not None:
            raise self._connect_raises
        self._connected = True

    def disconnect(self) -> None:
        self.disconnect_calls += 1
        self._connected = False

    def isConnected(self) -> bool:
        return self._connected

    def managedAccounts(self) -> list[str]:
        return self._managed

    def accountSummary(self, _account: str) -> list[Any]:
        return self._summary

    def positions(self, _account: str) -> list[Any]:
        return self._positions

    def openOrders(self) -> list[Any]:
        return self._open_orders


def _make_provider(ib: _FakeIB, *, account: str = "DU1234567") -> IBProvider:
    return IBProvider(
        host="localhost",
        port=4002,
        client_id=1,
        expected_account_id=account,
        connect_timeout=1.0,
        retry_max=1,
        retry_backoff=0.0,
        ib_factory=lambda: ib,
    )


# --- IB-01: connect + account verification -----------------------------------


async def test_connect_succeeds_when_account_is_managed() -> None:
    ib = _FakeIB(managed_accounts=["DU1234567"])
    provider = _make_provider(ib)
    await provider.connect()
    assert ib.connect_calls == 1
    assert ib.disconnect_calls == 0


async def test_connect_rejects_unexpected_account() -> None:
    ib = _FakeIB(managed_accounts=["U7777777"])  # live account, we expect paper
    provider = _make_provider(ib, account="DU1234567")
    with pytest.raises(IBConnectionError, match="not among"):
        await provider.connect()
    assert ib.disconnect_calls == 1


async def test_connect_retries_and_eventually_raises() -> None:
    ib = _FakeIB(connect_raises=ConnectionRefusedError("gateway down"))
    provider = IBProvider(
        host="localhost",
        port=4002,
        client_id=1,
        expected_account_id="DU1",
        connect_timeout=0.5,
        retry_max=3,
        retry_backoff=0.0,
        ib_factory=lambda: ib,
    )
    with pytest.raises(IBConnectionError, match="connect failed after 3 attempts"):
        await provider.connect()
    assert ib.connect_calls == 3


async def test_disconnect_is_idempotent() -> None:
    ib = _FakeIB(managed_accounts=["DU1234567"])
    provider = _make_provider(ib)
    await provider.connect()
    await provider.disconnect()
    await provider.disconnect()  # must not raise


# --- IB-02: read methods ----------------------------------------------------


async def test_read_methods_fail_before_connect() -> None:
    ib = _FakeIB(managed_accounts=["DU1234567"])
    provider = _make_provider(ib)
    with pytest.raises(IBConnectionError, match="not been called"):
        await provider.get_account_summary()
    with pytest.raises(IBConnectionError):
        await provider.get_positions()
    with pytest.raises(IBConnectionError):
        await provider.get_open_orders()


async def test_account_summary_keeps_only_numeric_values() -> None:
    summary = [
        SimpleNamespace(tag="NetLiquidation", value="125000.50"),
        SimpleNamespace(tag="BuyingPower", value="50000"),
        SimpleNamespace(tag="Currency", value="USD"),
    ]
    ib = _FakeIB(managed_accounts=["DU1234567"], account_summary=summary)
    provider = _make_provider(ib)
    await provider.connect()
    result = await provider.get_account_summary()
    assert result == {"NetLiquidation": 125000.50, "BuyingPower": 50000.0}


async def test_get_positions_maps_ib_insync_positions_to_dtos() -> None:
    positions = [
        SimpleNamespace(
            contract=SimpleNamespace(symbol="TSLA"),
            position=10,
            avgCost=240.5,
        ),
        SimpleNamespace(
            contract=SimpleNamespace(symbol="AAPL"),
            position=-5,
            avgCost=180.0,
        ),
    ]
    ib = _FakeIB(managed_accounts=["DU1234567"], positions=positions)
    provider = _make_provider(ib)
    await provider.connect()
    result = await provider.get_positions()
    assert result == [
        Position(symbol="TSLA", quantity=10, avg_price_usd=240.5),
        Position(symbol="AAPL", quantity=-5, avg_price_usd=180.0),
    ]


async def test_get_open_orders_returns_receipts() -> None:
    orders = [
        SimpleNamespace(orderId=1001, orderRef="k-abc"),
        SimpleNamespace(orderId=1002, orderRef=""),
    ]
    ib = _FakeIB(managed_accounts=["DU1234567"], open_orders=orders)
    provider = _make_provider(ib)
    await provider.connect()
    receipts = await provider.get_open_orders()
    assert len(receipts) == 2
    assert receipts[0].idempotency_key == "k-abc"
    assert receipts[0].external_id == "1001"
    # Empty orderRef → fall back to orderId as idempotency key.
    assert receipts[1].idempotency_key == "1002"


# --- Phase-6 write methods are currently gated ------------------------------


async def test_place_order_raises_not_implemented() -> None:
    ib = _FakeIB(managed_accounts=["DU1234567"])
    provider = _make_provider(ib)
    await provider.connect()
    order = ValidatedOrder(
        idempotency_key="k",
        event_id="e",
        strategy_id="s",
        trading_mode=TradingMode.PAPER,
        side=OrderSide.BUY,
        order_type=OrderType.MARKET,
        symbol="TSLA",
        quantity=1,
    )
    with pytest.raises(NotImplementedError, match="EXEC-01"):
        await provider.place_order(order)


async def test_cancel_all_raises_not_implemented() -> None:
    ib = _FakeIB(managed_accounts=["DU1234567"])
    provider = _make_provider(ib)
    await provider.connect()
    with pytest.raises(NotImplementedError, match="KILL-02"):
        await provider.cancel_all()


# --- Protocol conformance ---------------------------------------------------


def test_ib_provider_satisfies_broker_protocol() -> None:
    def _takes(p: BrokerProvider) -> BrokerProvider:
        return p

    provider = _make_provider(_FakeIB(managed_accounts=["DU1234567"]))
    _takes(provider)
