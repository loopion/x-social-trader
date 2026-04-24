"""Risk manager (INV-3) — must be traversed before any broker.place_order call.

Public exports are intentionally small: the executor builds a RiskManager via
`build_risk_manager(...)` and calls `validate(order, context, session)`.
"""

from backend.risk.factory import build_risk_manager
from backend.risk.manager import RiskManager
from backend.risk.models import (
    ProposedOrder,
    RuleCheckResult,
    ValidationContext,
    ValidationResult,
)

__all__ = [
    "ProposedOrder",
    "RiskManager",
    "RuleCheckResult",
    "ValidationContext",
    "ValidationResult",
    "build_risk_manager",
]
