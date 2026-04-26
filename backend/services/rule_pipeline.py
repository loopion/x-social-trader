"""Rule-engine pipeline worker (RULE-02 + RULE-04 wiring).

Consumes the Redis queue ``events`` populated by ``run_llm_pipeline``,
loads the matching ``Event`` from the DB, runs the rule engine, persists
all rule evaluations (INV-4), and submits the matched ``ProposedOrder``
through an executor (INV-1/2/3 still gate the actual broker call).

Per CLAUDE.md §3.2 the worker runs as its own process. The orchestrator
mirrors ``run_ingestion`` / ``run_llm_pipeline``: a fresh short-lived
session per iteration, kill-switch pre-check inside that session.

Why an ``executor_factory`` instead of a single executor instance?
``OrderExecutor`` carries a ``KillSwitchService`` which itself carries a
DB session — using a long-lived service against per-iteration sessions
leaks connections (the same trap that bit ``run_ingestion`` last week).
The factory lets the worker spin up an executor + kill switch bound to
the current session and drop both at iteration end.
"""

from __future__ import annotations

import os
from collections.abc import Awaitable, Callable
from dataclasses import dataclass
from typing import Any, cast

from redis.asyncio import Redis
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from backend.core.logging import get_logger
from backend.execution.context import build_validation_context
from backend.execution.executor import OrderExecutor, SubmissionRejected
from backend.kill_switch import KillSwitchService
from backend.kill_switch.service import EnvGetter
from backend.models.event import Event as DBEvent
from backend.models.rule_evaluation import RuleEvaluation as DBRuleEvaluation
from backend.providers.base import BrokerProvider
from backend.rules.engine import RuleEngine, RuleEngineOutcome
from backend.rules.store import RuleStore

log = get_logger("services.rule_pipeline")

REDIS_INPUT_QUEUE = "events"

ExecutorFactory = Callable[[AsyncSession], OrderExecutor]


def _default_env_getter() -> str | None:
    return os.environ.get("KILL_SWITCH")


@dataclass(frozen=True, slots=True)
class RulePipelineReport:
    evaluated: int
    matched: int
    submitted: int
    rejected: int
    stopped_reason: str | None


def _persist_evaluations(
    session: AsyncSession,
    *,
    event_id: str,
    outcome: RuleEngineOutcome,
) -> None:
    for record in outcome.evaluations:
        session.add(
            DBRuleEvaluation(
                event_id=event_id,
                rule_id=record.rule_id,
                rule_priority=record.rule_priority,
                inputs_hash=record.inputs_hash,
                inputs_json=record.inputs,
                outcome=record.outcome.value,
                proposed_order_json=(
                    record.proposed_order.model_dump(mode="json")
                    if record.proposed_order is not None
                    else None
                ),
            )
        )


async def run_rule_pipeline(
    *,
    rule_store: RuleStore,
    executor_factory: ExecutorFactory,
    broker: BrokerProvider,
    session_factory: async_sessionmaker[AsyncSession],
    redis_client: Redis,
    env_getter: EnvGetter = _default_env_getter,
    drain: bool = False,
    block_seconds: int = 1,
) -> RulePipelineReport:
    """Pop events, evaluate, submit. ``drain=True`` stops on empty queue."""
    evaluated = 0
    matched = 0
    submitted = 0
    rejected = 0
    stopped_reason: str | None = None

    while True:
        # Kill-switch pre-check (per-iteration session — see ingestion.py).
        async with session_factory() as session:
            kill_switch = KillSwitchService(
                session=session, redis_client=redis_client, env_getter=env_getter
            )
            state = await kill_switch.is_active()
        if state.active:
            stopped_reason = f"kill_switch_active:{state.source}"
            log.warning("rule_pipeline.stopped_kill_switch", source=state.source)
            break

        raw = await _pop(redis_client, drain=drain, block_seconds=block_seconds)
        if raw is None:
            if drain:
                break
            continue
        event_id = raw

        async with session_factory() as session:
            event_row = (
                await session.execute(select(DBEvent).where(DBEvent.event_id == event_id))
            ).scalar_one_or_none()
            if event_row is None:
                log.warning("rule_pipeline.event_not_found", event_id=event_id)
                continue

            outcome = RuleEngine(rule_store.get_rules()).evaluate(event_row)
            _persist_evaluations(session, event_id=event_id, outcome=outcome)
            evaluated += 1

            if outcome.matched is not None and outcome.matched.proposed_order is not None:
                matched += 1
                proposed = outcome.matched.proposed_order
                ctx = await build_validation_context(broker=broker, session=session)
                executor = executor_factory(session)
                try:
                    await executor.submit(proposed, ctx, session)
                    submitted += 1
                except SubmissionRejected as exc:
                    rejected += 1
                    log.info(
                        "rule_pipeline.submission_rejected",
                        event_id=event_id,
                        rule_id=outcome.matched.rule_id,
                        reason=str(exc)[:200],
                    )
            await session.commit()

    return RulePipelineReport(
        evaluated=evaluated,
        matched=matched,
        submitted=submitted,
        rejected=rejected,
        stopped_reason=stopped_reason,
    )


async def _pop(redis_client: Redis, *, drain: bool, block_seconds: int) -> str | None:
    if drain:
        raw = await cast("Awaitable[Any]", redis_client.lpop(REDIS_INPUT_QUEUE))
    else:
        raw = await cast(
            "Awaitable[Any]",
            redis_client.blpop([REDIS_INPUT_QUEUE], timeout=block_seconds),
        )
        if raw is not None:
            _, raw = raw
    if raw is None:
        return None
    if isinstance(raw, bytes):
        return raw.decode()
    return str(raw)


__all__ = [
    "REDIS_INPUT_QUEUE",
    "ExecutorFactory",
    "RulePipelineReport",
    "run_rule_pipeline",
]
