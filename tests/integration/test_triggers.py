"""INV-4 — audit tables must reject UPDATE and DELETE at the DB layer.

We insert the minimum row in each audit table, then verify that any attempt to
mutate or remove it raises an error whose message mentions 'append-only'.
"""

from __future__ import annotations

from datetime import UTC, datetime
from typing import Any

import pytest
from sqlalchemy import text
from sqlalchemy.exc import IntegrityError, OperationalError
from sqlalchemy.ext.asyncio import AsyncSession

from backend.models import (
    AUDIT_TABLES,
    Event,
    Fill,
    KillSwitchEvent,
    LLMDecision,
    Order,
    RawTweet,
    RuleEvaluation,
)


async def _insert_parents(session: AsyncSession) -> dict[str, Any]:
    """Insert the chain raw_tweet → llm_decision → event → order → fill deps."""
    tweet = RawTweet(
        tweet_id="t1",
        x_user_id="x1",
        username="u",
        content="c",
        raw_json={},
        received_at=datetime.now(UTC),
    )
    session.add(tweet)
    await session.flush()

    decision = LLMDecision(
        raw_tweet_id=tweet.id,
        prompt_version="v1",
        model="m",
        provider="p",
        prompt="prompt",
        raw_response="{}",
        status="success",
    )
    session.add(decision)
    await session.flush()

    event = Event(
        event_id="e1",
        raw_tweet_id=tweet.id,
        llm_decision_id=decision.id,
        ticker="TSLA",
        intent="bullish",
        confidence=0.8,
        time_horizon="intraday",
    )
    session.add(event)
    await session.flush()

    order = Order(
        idempotency_key="k1",
        event_id=event.event_id,
        strategy_id="strat",
        trading_mode="paper",
        side="buy",
        order_type="market",
        symbol="TSLA",
        quantity=1,
    )
    session.add(order)
    await session.flush()

    fill = Fill(
        order_id=order.id,
        external_fill_id="f1",
        symbol="TSLA",
        quantity=1,
        price=100.0,
        filled_at=datetime.now(UTC),
    )
    session.add(fill)

    rule_eval = RuleEvaluation(
        event_id=event.event_id,
        rule_id="r1",
        rule_priority=1,
        inputs_hash="h",
        inputs_json={},
        outcome="matched",
    )
    session.add(rule_eval)

    ks_event = KillSwitchEvent(activated=True, trigger="manual", actor="pytest")
    session.add(ks_event)

    await session.commit()
    return {
        "llm_decisions": decision.id,
        "rule_evaluations": rule_eval.id,
        "orders": order.id,
        "fills": fill.id,
        "kill_switch_events": ks_event.id,
    }


@pytest.mark.parametrize("table", AUDIT_TABLES)
async def test_audit_table_rejects_update(session: AsyncSession, table: str) -> None:
    ids = await _insert_parents(session)
    row_id = ids[table]
    with pytest.raises((IntegrityError, OperationalError)) as excinfo:
        await session.execute(text(f"UPDATE {table} SET id = id WHERE id = :id"), {"id": row_id})
        await session.commit()
    assert "append-only" in str(excinfo.value).lower()


@pytest.mark.parametrize("table", AUDIT_TABLES)
async def test_audit_table_rejects_delete(session: AsyncSession, table: str) -> None:
    ids = await _insert_parents(session)
    row_id = ids[table]
    with pytest.raises((IntegrityError, OperationalError)) as excinfo:
        await session.execute(text(f"DELETE FROM {table} WHERE id = :id"), {"id": row_id})
        await session.commit()
    assert "append-only" in str(excinfo.value).lower()
