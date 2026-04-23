# AGENTS.md — x-social-trader

> Social-media-driven automated trading system. Python 3.11+ / FastAPI / SQLAlchemy / ib_insync / React + Vite + TS.
> **This system trades real capital.** Every code change must be evaluated against the safety invariants below.

---

## Non-negotiable safety invariants

Violating any of these is a critical bug. If a user request conflicts with an invariant, refuse and explain.

- **INV-1 No live orders without double opt-in.** Live execution requires `TRADING_MODE == "live"` AND `PAPER_TRADING == False` AND `KILL_SWITCH_ACTIVE == False`. Defaults: `TRADING_MODE=paper`, `PAPER_TRADING=True`.
- **INV-2 Kill switch.** Three independent kill paths (env var `KILL_SWITCH=1`, `POST /kill-switch`, UI button). Activation cancels all open IB orders, blocks new submissions (HTTP 423), requires manual reset with audit log.
- **INV-3 Risk manager is mandatory.** Every order must pass `risk_manager.validate()` before `broker.place_order()`. No bypass, not even for tests. Risk manager test coverage must be 100%.
- **INV-4 Audit tables are append-only.** Tables `llm_decisions`, `rule_evaluations`, `orders`, `fills`, `trade_journal` — no `UPDATE` or `DELETE` in application code. No Alembic migrations that reduce history.
- **INV-5 No secrets in code or logs.** All secrets via env vars + `.env` (gitignored). `StructlogRedactor` must filter API keys, passwords, tokens, account numbers from logs.
- **INV-6 Idempotence.** Same `tweet_id` or `event_id` must never produce a second order. Enforce via DB unique constraint + application check.
- **INV-7 Backtest before live.** No strategy goes `TRADING_MODE=live` without documented backtest results (≥30 days) in `/backtests/<strategy>/<date>.md`.

---

## Architecture constraints an agent will miss

- **Process isolation.** Each component (api, ingestion, llm_worker, executor, telegram_bot) runs as a separate process. Never execute trading code inside the `api` process.
- **Provider imports are scoped.** `ib_insync` and twitterapi.io SDK must only be imported inside `providers/`. All business logic depends on protocol interfaces (`SocialFeedProvider`, `LLMProvider`, `BrokerProvider`), never concrete implementations.
- **No `Base.metadata.create_all()` outside tests.** Use Alembic migrations exclusively for schema changes.
- **No Telegram command that places an order.** Telegram commands are limited to `/status`, `/kill`, `/ack <event_id>`.

---

## Stack & tooling

| Layer | Tech |
|-------|------|
| Backend | Python 3.11+, FastAPI, SQLAlchemy, Alembic, Redis + ARQ |
| Broker | ib_insync (async mode) |
| Social feed | twitterapi.io (WebSocket preferred) |
| Frontend | React, Vite, TypeScript (strict), TanStack Query, Zustand |
| API client | Generated from OpenAPI via `openapi-typescript` |

### Python conventions
- Lint + format: `ruff`. Types: `mypy --strict`.
- No `print` — use `structlog` (JSON structured logs).
- Type hints everywhere including returns. Async by default for I/O.
- Pydantic or dataclasses for data; no raw `dict` in internal APIs.
- Files ≤ 300 lines, one concept per file.

### TypeScript conventions
- Strict mode. No `any`. No `console.log` in production (enforced by lint).

### Git conventions
- Branches: `feat/<ticket-id>-slug`, `fix/...`, `chore/...`
- Commits: Conventional Commits (`feat:`, `fix:`, `chore:`, `refactor:`, `test:`, `docs:`)

---

## Testing

- `pytest`, global coverage ≥ 80%, **risk_manager coverage = 100%**.
- Provider mocks live in `tests/mocks/`.
- No test may call real IB in live mode. Ever.
- E2E golden path: tweet → order (paper) → simulated fill, runs in CI.
- Touching risk manager code without updating its tests is a bug.

---

## Development phase order

Phases must be followed in sequence. Do not jump ahead.

1. Bootstrap (repo, pyproject.toml, docker-compose, pre-commit, CI)
2. Persistence (SQLAlchemy + Alembic + models + migrations + seed)
3. Observability (structlog, /metrics, /health, /ready)
4. Provider abstractions (interfaces + mocks + tests)
5. IB read-only (connect, read positions/account, **no orders**)
6. Paper trading (orders in paper only, risk manager, kill switch)
7. Ingestion (twitterapi.io WebSocket + reconnection + raw_tweets persistence)
8. LLM pipeline (prompt v1, strict JSON parsing, llm_decisions journal, budget)
9. Rule engine + end-to-end paper integration
10. Backtesting (replay engine on historical raw_tweets)
11. Telegram alerts (outbound only)
12. Advanced UI (dashboard, journal, manual controls, kill switch button)
13. Telegram commands (inbound, limited)
14. Live cutover (after documented backtest + manual review + low capital cap)

---

## Do not

- Invent undocumented twitterapi.io or IB endpoints — ask the user.
- Set `TRADING_MODE=live` in any example, doc, or test default.
- Commit `.env` or files containing secrets.
- Disable a lint/mypy rule without a justification comment.
- Produce `UPDATE`/`DELETE` on audit tables (INV-4).

## When to stop and ask

- Ambiguity on a trading rule, threshold, or priority.
- Need for a major unplanned external dependency.
- Conflict between a user request and a safety invariant.
- Irreversible change (destructive migration, audit schema change).

**When in doubt, choose safety over functionality.** A missed trade is always less severe than an unwanted one.
