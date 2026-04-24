"""Order execution pipeline (EXEC-01 + EXEC-02).

`OrderExecutor.submit` is the single entry point. It enforces (in order):

1. **INV-2** — kill switch check (any of env / Redis / DB).
2. **INV-1** — live-mode double opt-in (trading_mode=live AND paper_trading=False).
3. **INV-3** — `risk_manager.validate(...)` with audit persistence.
4. **EXEC-02** — deterministic idempotency key = f"{event_id}:{strategy_id}".
5. Broker submission.
6. Persist the `orders` row (append-only, INV-4) + structlog + Prometheus.
"""

from backend.execution.context import (
    ValidationContextError,
    build_validation_context,
)
from backend.execution.executor import (
    KillSwitchActiveError,
    LiveModeNotPermittedError,
    OrderExecutor,
    SubmissionRejected,
    SubmissionResult,
    compute_idempotency_key,
    persist_fill,
)

__all__ = [
    "KillSwitchActiveError",
    "LiveModeNotPermittedError",
    "OrderExecutor",
    "SubmissionRejected",
    "SubmissionResult",
    "ValidationContextError",
    "build_validation_context",
    "compute_idempotency_key",
    "persist_fill",
]
