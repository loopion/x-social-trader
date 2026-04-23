"""Import all models here so `Base.metadata` sees them for Alembic autogenerate."""

from backend.models.alias import Alias
from backend.models.base import Base
from backend.models.event import Event
from backend.models.fill import Fill
from backend.models.kill_switch_event import KillSwitchEvent
from backend.models.llm_decision import LLMDecision
from backend.models.order import Order
from backend.models.position import Position
from backend.models.raw_tweet import RawTweet
from backend.models.risk_limit import RiskLimit
from backend.models.rule_evaluation import RuleEvaluation
from backend.models.settings import Settings
from backend.models.watched_account import WatchedAccount

__all__ = [
    "Alias",
    "Base",
    "Event",
    "Fill",
    "KillSwitchEvent",
    "LLMDecision",
    "Order",
    "Position",
    "RawTweet",
    "RiskLimit",
    "RuleEvaluation",
    "Settings",
    "WatchedAccount",
]

# Tables protected by INV-4 append-only triggers (see migration 0001).
AUDIT_TABLES: tuple[str, ...] = (
    "llm_decisions",
    "rule_evaluations",
    "orders",
    "fills",
    "kill_switch_events",
)
