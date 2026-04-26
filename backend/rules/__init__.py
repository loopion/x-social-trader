"""Rule engine package — declarative YAML rules → ``ProposedOrder`` (Phase 9)."""

from backend.rules.engine import (
    RuleEngine,
    RuleEngineOutcome,
    RuleEvaluationRecord,
    build_proposed_order,
)
from backend.rules.loader import RuleLoadError, load_rules_from_dir
from backend.rules.models import ActionSpec, ConditionSpec, RuleSpec
from backend.rules.store import RuleStore

__all__ = [
    "ActionSpec",
    "ConditionSpec",
    "RuleEngine",
    "RuleEngineOutcome",
    "RuleEvaluationRecord",
    "RuleLoadError",
    "RuleSpec",
    "RuleStore",
    "build_proposed_order",
    "load_rules_from_dir",
]
