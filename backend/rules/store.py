"""In-memory rule cache with hot-reload (RULE-03)."""

from __future__ import annotations

from pathlib import Path

from backend.core.logging import get_logger
from backend.rules.loader import load_rules_from_dir
from backend.rules.models import RuleSpec

log = get_logger("rules.store")


class RuleStore:
    """Holds the current ``list[RuleSpec]`` and reloads from disk on demand.

    Thread-safe enough for our process-per-worker model: ``reload`` swaps
    the underlying list atomically by reference; engines pull a fresh
    ``get_rules()`` per evaluation, so no read tears.
    """

    def __init__(self, directory: Path | str) -> None:
        self._dir = Path(directory)
        self._rules: list[RuleSpec] = []

    def reload(self) -> int:
        """Re-read all YAML files from disk. Returns the new count.

        Raises ``RuleLoadError`` on parse / schema failure — the previous
        ``_rules`` list stays in place so a bad reload does not nuke a
        running pipeline.
        """
        new_rules = load_rules_from_dir(self._dir)
        self._rules = new_rules
        log.info("rules.store.reloaded", count=len(new_rules), directory=str(self._dir))
        return len(new_rules)

    def get_rules(self) -> list[RuleSpec]:
        return list(self._rules)

    @property
    def directory(self) -> Path:
        return self._dir
