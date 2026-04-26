"""Load + validate rule YAML files from disk (RULE-01)."""

from __future__ import annotations

from pathlib import Path
from typing import Any

import yaml
from pydantic import ValidationError

from backend.core.logging import get_logger
from backend.rules.models import RuleSpec

log = get_logger("rules.loader")


class RuleLoadError(RuntimeError):
    """Raised when a rule file is malformed, fails schema validation, or
    when two rule files declare the same ``id`` (ambiguous priority).
    """


def _parse_one(path: Path) -> RuleSpec:
    try:
        with path.open("r", encoding="utf-8") as fh:
            data: Any = yaml.safe_load(fh)
    except yaml.YAMLError as exc:
        raise RuleLoadError(f"YAML parse error in {path}: {exc}") from exc
    if not isinstance(data, dict):
        raise RuleLoadError(f"{path}: top-level YAML node must be a mapping")
    try:
        return RuleSpec.model_validate(data)
    except ValidationError as exc:
        raise RuleLoadError(f"{path}: schema validation failed: {exc}") from exc


def load_rules_from_dir(directory: Path | str) -> list[RuleSpec]:
    """Load every ``*.yaml`` / ``*.yml`` file under ``directory``.

    Files starting with ``_`` are skipped (convenient for drafts).
    Disabled rules are loaded so they can be hot-flipped at runtime.
    Result is sorted by descending priority then id for deterministic
    iteration in the engine.
    """
    base = Path(directory)
    if not base.is_dir():
        raise RuleLoadError(f"rules directory not found: {base}")

    paths = sorted(p for p in base.iterdir() if p.suffix in {".yaml", ".yml"})
    rules: list[RuleSpec] = []
    seen: set[str] = set()
    for path in paths:
        if path.name.startswith("_"):
            continue
        rule = _parse_one(path)
        if rule.id in seen:
            raise RuleLoadError(f"duplicate rule id '{rule.id}' (in {path})")
        seen.add(rule.id)
        rules.append(rule)

    rules.sort(key=lambda r: (-r.priority, r.id))
    log.info("rules.loader.loaded", count=len(rules), directory=str(base))
    return rules
