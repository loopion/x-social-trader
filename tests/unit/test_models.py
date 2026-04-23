from __future__ import annotations

from backend.models import AUDIT_TABLES, Base


def test_all_expected_tables_registered() -> None:
    expected = {
        "aliases",
        "events",
        "fills",
        "kill_switch_events",
        "llm_decisions",
        "orders",
        "positions",
        "raw_tweets",
        "risk_limits",
        "rule_evaluations",
        "settings",
        "watched_accounts",
    }
    assert expected.issubset(Base.metadata.tables.keys())


def test_audit_tables_listed_are_actual_tables() -> None:
    """AUDIT_TABLES is the source of truth for INV-4 — it must match real tables."""
    for name in AUDIT_TABLES:
        assert name in Base.metadata.tables, f"{name} missing from metadata"


def test_audit_tables_have_created_at_but_no_updated_at() -> None:
    """INV-4 requires no `updated_at` on audit tables (immutable rows)."""
    for name in AUDIT_TABLES:
        columns = {c.name for c in Base.metadata.tables[name].columns}
        assert "created_at" in columns, f"{name} missing created_at"
        assert "updated_at" not in columns, f"{name} has updated_at (forbidden by INV-4)"


def test_orders_has_unique_idempotency_key() -> None:
    """INV-6: orders must reject duplicate idempotency_key at DB level."""
    orders = Base.metadata.tables["orders"]
    idem = orders.columns["idempotency_key"]
    unique_indexes = [
        ix for ix in orders.indexes if "idempotency_key" in [c.name for c in ix.columns]
    ]
    assert idem.unique or any(ix.unique for ix in unique_indexes)


def test_events_has_unique_event_id() -> None:
    """INV-6: events.event_id unique (used downstream as FK and dedupe key)."""
    events = Base.metadata.tables["events"]
    eid = events.columns["event_id"]
    unique_indexes = [ix for ix in events.indexes if "event_id" in [c.name for c in ix.columns]]
    assert eid.unique or any(ix.unique for ix in unique_indexes)


def test_raw_tweets_has_unique_tweet_id() -> None:
    """INV-6: no duplicate tweets even if the WS re-delivers."""
    raw = Base.metadata.tables["raw_tweets"]
    tid = raw.columns["tweet_id"]
    unique_indexes = [ix for ix in raw.indexes if "tweet_id" in [c.name for c in ix.columns]]
    assert tid.unique or any(ix.unique for ix in unique_indexes)
