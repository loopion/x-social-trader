"""Admin rules API — RULE-03 hot reload."""

from __future__ import annotations

from collections.abc import Iterator
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from backend.api.main import app
from backend.rules.store import RuleStore

VALID_YAML_BULL = """
id: rule_bull
priority: 50
enabled: true
conditions:
  - field: intent
    op: eq
    value: bullish
action:
  side: buy
  order_type: market
  quantity: 1
  reference_price_usd: 100.0
  strategy_id: rule_bull
"""

VALID_YAML_BEAR = """
id: rule_bear
priority: 80
enabled: false
conditions:
  - field: intent
    op: eq
    value: bearish
action:
  side: sell
  order_type: market
  quantity: 1
  reference_price_usd: 100.0
  strategy_id: rule_bear
"""

INVALID_YAML = """
id: bad
priority: 1
enabled: true
conditions:
  - field: intent
    op: eq
    value: bullish
action:
  side: buy
  # order_type missing -> schema fail
  quantity: 1
  reference_price_usd: 100.0
  strategy_id: bad
"""


@pytest.fixture
def rules_dir(tmp_path: Path) -> Path:
    return tmp_path


@pytest.fixture
def patched_client(rules_dir: Path) -> Iterator[TestClient]:
    """Inject a RuleStore pointed at ``rules_dir`` so we control the input."""
    with TestClient(app) as client:
        client.app.state.rule_store = RuleStore(rules_dir)  # type: ignore[attr-defined]
        yield client


def test_get_returns_empty_when_directory_is_empty(patched_client: TestClient) -> None:
    resp = patched_client.get("/admin/rules")
    assert resp.status_code == 200
    body = resp.json()
    assert body["count"] == 0
    assert body["rules"] == []


def test_reload_picks_up_new_rule_files(patched_client: TestClient, rules_dir: Path) -> None:
    (rules_dir / "bull.yaml").write_text(VALID_YAML_BULL, encoding="utf-8")
    resp = patched_client.post("/admin/rules/reload")
    assert resp.status_code == 200
    assert resp.json()["loaded"] == 1

    list_resp = patched_client.get("/admin/rules")
    payload = list_resp.json()
    assert payload["count"] == 1
    assert payload["rules"][0]["id"] == "rule_bull"


def test_reload_swaps_atomically_on_subsequent_changes(
    patched_client: TestClient, rules_dir: Path
) -> None:
    (rules_dir / "bull.yaml").write_text(VALID_YAML_BULL, encoding="utf-8")
    patched_client.post("/admin/rules/reload")
    (rules_dir / "bear.yaml").write_text(VALID_YAML_BEAR, encoding="utf-8")
    resp = patched_client.post("/admin/rules/reload")
    assert resp.json()["loaded"] == 2

    listing = patched_client.get("/admin/rules").json()
    ids = [r["id"] for r in listing["rules"]]
    # Higher-priority rule first.
    assert ids == ["rule_bear", "rule_bull"]


def test_reload_returns_400_on_invalid_rule_and_keeps_old_set(
    patched_client: TestClient, rules_dir: Path
) -> None:
    (rules_dir / "bull.yaml").write_text(VALID_YAML_BULL, encoding="utf-8")
    patched_client.post("/admin/rules/reload")

    (rules_dir / "bad.yaml").write_text(INVALID_YAML, encoding="utf-8")
    resp = patched_client.post("/admin/rules/reload")
    assert resp.status_code == 400
    assert "schema validation failed" in resp.json()["detail"]

    # Old set still served.
    listing = patched_client.get("/admin/rules").json()
    assert listing["count"] == 1
    assert listing["rules"][0]["id"] == "rule_bull"


def test_reload_returns_503_when_store_not_initialised() -> None:
    with TestClient(app) as client:
        client.app.state.rule_store = None  # type: ignore[attr-defined]
        resp = client.post("/admin/rules/reload")
        assert resp.status_code == 503
