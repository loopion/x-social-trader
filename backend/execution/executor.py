"""OrderExecutor — the sole path to `broker.place_order` (INV-1 + INV-2 + INV-3)."""

from __future__ import annotations

from dataclasses import dataclass

from sqlalchemy.ext.asyncio import AsyncSession

from backend.core.logging import get_logger
from backend.core.metrics import orders_submitted_total
from backend.core.settings import Settings
from backend.kill_switch import KillSwitchService
from backend.models.enums import TradingMode
from backend.models.fill import Fill as DBFill
from backend.models.order import Order as DBOrder
from backend.providers import (
    BrokerProvider,
    OrderReceipt,
    ValidatedOrder,
)
from backend.providers import (
    Fill as BrokerFill,
)
from backend.risk import (
    ProposedOrder,
    RiskManager,
    ValidationContext,
    ValidationResult,
)

log = get_logger("execution.executor")


# -----------------------------------------------------------------------------
# Exceptions
# -----------------------------------------------------------------------------


class SubmissionRejected(RuntimeError):
    """Parent class — one of the INV gates blocked the order."""

    def __init__(self, message: str, *, validation: ValidationResult | None = None) -> None:
        super().__init__(message)
        self.validation = validation


class KillSwitchActiveError(SubmissionRejected):
    """INV-2 — kill switch is on; HTTP layer should reply 423 Locked."""


class LiveModeNotPermittedError(SubmissionRejected):
    """INV-1 — live order without the DB + env double opt-in."""


# -----------------------------------------------------------------------------
# Result
# -----------------------------------------------------------------------------


@dataclass(frozen=True, slots=True)
class SubmissionResult:
    receipt: OrderReceipt
    validated_order: ValidatedOrder
    db_order_id: int


# -----------------------------------------------------------------------------
# Helpers
# -----------------------------------------------------------------------------


def compute_idempotency_key(event_id: str, strategy_id: str) -> str:
    """EXEC-02 — deterministic derivation used by DB unique constraint + risk."""
    return f"{event_id}:{strategy_id}"


# -----------------------------------------------------------------------------
# Executor
# -----------------------------------------------------------------------------


class OrderExecutor:
    def __init__(
        self,
        *,
        broker: BrokerProvider,
        risk_manager: RiskManager,
        kill_switch: KillSwitchService,
        settings: Settings,
    ) -> None:
        self._broker = broker
        self._risk = risk_manager
        self._kill = kill_switch
        self._settings = settings

    async def submit(
        self,
        proposed: ProposedOrder,
        context: ValidationContext,
        session: AsyncSession,
    ) -> SubmissionResult:
        """Submit one order through the full invariant chain."""
        # --- INV-2 ----------------------------------------------------------
        state = await self._kill.is_active()
        if state.active:
            log.warning(
                "order_blocked_kill_switch",
                event_id=proposed.event_id,
                kill_switch_source=state.source,
            )
            raise KillSwitchActiveError(f"kill switch active (source={state.source})")

        # --- INV-1 ----------------------------------------------------------
        if proposed.trading_mode == TradingMode.LIVE and not self._settings.is_live_trading:
            raise LiveModeNotPermittedError(
                "INV-1: live order requires TRADING_MODE=live AND PAPER_TRADING=False",
            )

        # --- INV-3 ----------------------------------------------------------
        validation = await self._risk.validate(proposed, context, session)
        if not validation.ok:
            reasons = "; ".join(f"{f.rule_name}: {f.reason}" for f in validation.failures)
            log.info(
                "order_rejected_by_risk",
                event_id=proposed.event_id,
                failed=len(validation.failures),
            )
            raise SubmissionRejected(
                f"risk manager rejected: {reasons}",
                validation=validation,
            )

        # --- Build ValidatedOrder + broker submission ----------------------
        idempotency_key = compute_idempotency_key(proposed.event_id, proposed.strategy_id)
        validated = ValidatedOrder(
            idempotency_key=idempotency_key,
            event_id=proposed.event_id,
            strategy_id=proposed.strategy_id,
            trading_mode=proposed.trading_mode,
            side=proposed.side,
            order_type=proposed.order_type,
            symbol=proposed.symbol,
            quantity=proposed.quantity,
            limit_price=proposed.limit_price,
        )
        receipt = await self._broker.place_order(validated)

        # --- Persist orders row (append-only, INV-4) -----------------------
        db_order = DBOrder(
            idempotency_key=idempotency_key,
            event_id=proposed.event_id,
            strategy_id=proposed.strategy_id,
            external_id=receipt.external_id,
            trading_mode=proposed.trading_mode.value,
            side=proposed.side.value,
            order_type=proposed.order_type.value,
            symbol=proposed.symbol,
            quantity=proposed.quantity,
            limit_price=proposed.limit_price,
        )
        session.add(db_order)
        await session.flush()

        orders_submitted_total.labels(mode=proposed.trading_mode.value).inc()
        log.info(
            "order_submitted",
            event_id=proposed.event_id,
            idempotency_key=idempotency_key,
            external_id=receipt.external_id,
            symbol=proposed.symbol,
            quantity=proposed.quantity,
        )

        return SubmissionResult(
            receipt=receipt,
            validated_order=validated,
            db_order_id=db_order.id,
        )


# -----------------------------------------------------------------------------
# Fill persistence — callable from the fills-listener worker (phase 6 wiring)
# -----------------------------------------------------------------------------


async def persist_fill(
    broker_fill: BrokerFill,
    db_order: DBOrder,
    session: AsyncSession,
) -> DBFill:
    """Insert one `fills` audit row (INV-4 append-only)."""
    row = DBFill(
        order_id=db_order.id,
        external_fill_id=broker_fill.external_fill_id,
        symbol=broker_fill.symbol,
        quantity=broker_fill.quantity,
        price=broker_fill.price,
        commission_usd=broker_fill.commission_usd,
        filled_at=broker_fill.filled_at,
    )
    session.add(row)
    await session.flush()
    return row
