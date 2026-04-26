"""Rule YAML loader tests (RULE-01)."""

from __future__ import annotations

from pathlib import Path

import pytest

from backend.models.enums import OrderSide, OrderType, TradingMode
from backend.rules.loader import RuleLoadError, load_rules_from_dir

VALID_YAML = """
id: r1
priority: 50
enabled: true
description: example
conditions:
  - field: intent
    op: eq
    value: bullish
  - field: confidence
    op: gte
    value: 0.5
action:
  trading_mode: paper
  side: buy
  order_type: market
  quantity: 1
  reference_price_usd: 100.0
  strategy_id: r1_strat
"""

DISABLED_YAML = """
id: r2
priority: 99
enabled: false
conditions:
  - field: ticker
    op: eq
    value: TSLA
action:
  side: sell
  order_type: market
  quantity: 1
  reference_price_usd: 100.0
  strategy_id: r2_strat
"""


def _write(tmp_path: Path, name: str, body: str) -> None:
    (tmp_path / name).write_text(body, encoding="utf-8")


# --- Happy path ----------------------------------------------------------


def test_loader_returns_rules_sorted_by_priority(tmp_path: Path) -> None:
    _write(tmp_path, "a.yaml", VALID_YAML)
    _write(tmp_path, "b.yaml", DISABLED_YAML)
    rules = load_rules_from_dir(tmp_path)
    # priority 99 comes before priority 50 (descending)
    assert [r.id for r in rules] == ["r2", "r1"]
    assert rules[0].action.side is OrderSide.SELL
    assert rules[1].action.trading_mode is TradingMode.PAPER
    assert rules[0].enabled is False  # disabled rules still load


def test_loader_skips_underscore_prefixed_files(tmp_path: Path) -> None:
    _write(tmp_path, "a.yaml", VALID_YAML)
    _write(tmp_path, "_draft.yaml", VALID_YAML)
    rules = load_rules_from_dir(tmp_path)
    assert len(rules) == 1


def test_loader_accepts_yml_extension(tmp_path: Path) -> None:
    _write(tmp_path, "a.yml", VALID_YAML)
    rules = load_rules_from_dir(tmp_path)
    assert rules[0].action.order_type is OrderType.MARKET


# --- Failure modes -------------------------------------------------------


def test_loader_rejects_missing_directory(tmp_path: Path) -> None:
    with pytest.raises(RuleLoadError, match="not found"):
        load_rules_from_dir(tmp_path / "nope")


def test_loader_rejects_non_mapping_top_level(tmp_path: Path) -> None:
    _write(tmp_path, "bad.yaml", "- 1\n- 2\n")
    with pytest.raises(RuleLoadError, match="must be a mapping"):
        load_rules_from_dir(tmp_path)


def test_loader_rejects_invalid_yaml(tmp_path: Path) -> None:
    # Unbalanced bracket → genuine YAML parse error.
    _write(tmp_path, "bad.yaml", "id: r1\nconditions: [\n")
    with pytest.raises(RuleLoadError, match="YAML parse error"):
        load_rules_from_dir(tmp_path)


def test_loader_rejects_unknown_field(tmp_path: Path) -> None:
    _write(
        tmp_path,
        "bad.yaml",
        VALID_YAML.replace("description: example", "description: example\nbogus: 1"),
    )
    with pytest.raises(RuleLoadError, match="schema validation failed"):
        load_rules_from_dir(tmp_path)


def test_loader_rejects_duplicate_ids(tmp_path: Path) -> None:
    _write(tmp_path, "a.yaml", VALID_YAML)
    _write(tmp_path, "b.yaml", VALID_YAML)  # same id 'r1'
    with pytest.raises(RuleLoadError, match="duplicate rule id"):
        load_rules_from_dir(tmp_path)


def test_loader_rejects_empty_conditions(tmp_path: Path) -> None:
    _write(
        tmp_path,
        "bad.yaml",
        VALID_YAML.replace(
            "conditions:\n  - field: intent\n    op: eq\n    value: bullish",
            "conditions: []",
        ).replace("  - field: confidence\n    op: gte\n    value: 0.5\n", ""),
    )
    with pytest.raises(RuleLoadError, match="schema validation failed"):
        load_rules_from_dir(tmp_path)
