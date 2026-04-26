"""trade_journal view (CLAUDE.md §4 + RULE-04)

Revision ID: 8a1d27bc4f30
Revises: 3253d00015fe
Create Date: 2026-04-26 09:00:00.000000
"""

from __future__ import annotations

from collections.abc import Sequence

from alembic import op

# revision identifiers, used by Alembic.
revision: str = "8a1d27bc4f30"  # pragma: allowlist secret
down_revision: str | None = "3253d00015fe"  # pragma: allowlist secret
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


_VIEW_SQL = """
CREATE VIEW trade_journal AS
SELECT
    e.event_id              AS event_id,
    e.ticker                AS ticker,
    e.intent                AS intent,
    e.confidence            AS confidence,
    e.time_horizon          AS time_horizon,
    rt.tweet_id             AS tweet_id,
    rt.username             AS username,
    rt.received_at          AS tweet_received_at,
    ld.id                   AS llm_decision_id,
    ld.model                AS llm_model,
    ld.prompt_version       AS llm_prompt_version,
    ld.cost_usd             AS llm_cost_usd,
    o.id                    AS order_id,
    o.idempotency_key       AS idempotency_key,
    o.external_id           AS order_external_id,
    o.trading_mode          AS trading_mode,
    o.side                  AS order_side,
    o.order_type            AS order_type,
    o.symbol                AS order_symbol,
    o.quantity              AS order_quantity,
    o.created_at            AS order_created_at,
    f.id                    AS fill_id,
    f.external_fill_id      AS external_fill_id,
    f.price                 AS fill_price,
    f.commission_usd        AS fill_commission_usd,
    f.filled_at             AS filled_at
FROM events e
LEFT JOIN raw_tweets    rt ON rt.id = e.raw_tweet_id
LEFT JOIN llm_decisions ld ON ld.id = e.llm_decision_id
LEFT JOIN orders        o  ON o.event_id = e.event_id
LEFT JOIN fills         f  ON f.order_id = o.id;
"""


def upgrade() -> None:
    op.execute(_VIEW_SQL)


def downgrade() -> None:
    op.execute("DROP VIEW IF EXISTS trade_journal")
