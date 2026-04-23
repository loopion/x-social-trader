# x-social-trader

Système qui surveille X (Twitter), fait passer les tweets pertinents dans un pipeline LLM, applique un moteur de règles + risk manager, et exécute des ordres via Interactive Brokers — en **paper trading par défaut**.

- **Invariants de sécurité** : voir [`CLAUDE.md`](./CLAUDE.md) §2 (INV-1 à INV-7).
- **Backlog** : voir [`BACKLOG.md`](./BACKLOG.md). Les phases sont exécutées dans l'ordre, sans anticipation.
- **Statut** : phase 1 (Bootstrap).

## Prérequis

- Python 3.11+
- [`uv`](https://docs.astral.sh/uv/) — `curl -LsSf https://astral.sh/uv/install.sh | sh`
- Node 20+
- Docker + Docker Compose

## Démarrage local (< 10 min)

```bash
git clone https://github.com/loopion/x-social-trader.git
cd x-social-trader
cp .env.example .env   # remplir les valeurs locales
```

### Backend

```bash
uv sync --all-groups
uv run ruff check .
uv run ruff format --check .
uv run mypy backend/
make migrate                  # alembic upgrade head
make seed                     # idempotent seed (settings + demo accounts + aliases)
uv run pytest
uv run uvicorn backend.api.main:app --reload
# → http://localhost:8000/health
```

### Observabilité

| Endpoint | Rôle |
|---|---|
| `GET /health` | Liveness — toujours 200 si le process répond. |
| `GET /ready` | Readiness — vérifie DB (SQLite/Postgres) + Redis, retourne 503 si une dépendance est en panne. |
| `GET /metrics` | Scrape Prometheus — métriques préfixées `xst_…` (counters, histogrammes, gauges). |

Dashboard Grafana : `ops/grafana/x-social-trader.json` (importable via l'UI Grafana). Logs structlog JSON avec redaction automatique des clés sensibles (INV-5).

### Migrations

```bash
make migrate                           # upgrade head
make migrate-down                      # downgrade one revision
make migrate-new msg='add X to Y'      # autogenerate new revision
```

Les tables `llm_decisions`, `rule_evaluations`, `orders`, `fills`, `kill_switch_events` sont protégées par des triggers SQLite `BEFORE UPDATE/DELETE` qui rejettent toute mutation (INV-4). Toute migration qui tente de les modifier doit être revue attentivement.

### Frontend

```bash
cd frontend
npm install
npm run type-check
npm run dev
# → http://localhost:5173
```

### Stack complète (Docker)

```bash
docker compose up --build
# api         → http://localhost:8000/health
# frontend    → http://localhost:5173
# redis       → localhost:6379
```

### Pre-commit

```bash
uv run pre-commit install
uv run pre-commit run --all-files
```

## Architecture

Cinq processus indépendants orchestrés par `docker compose` :

| Service | Rôle | Phase |
|---|---|---|
| `api` | FastAPI (lecture, config, WebSocket pub/sub) | 1 |
| `ingestion` | WebSocket twitterapi.io → `raw_tweets` | 7 |
| `llm_worker` | Analyse sémantique, queue ARQ | 8 |
| `executor` | ib_insync, risk manager, kill switch | 6 |
| `telegram_bot` | Alertes sortantes + commandes limitées | 11 + 13 |

Diagramme complet dans [`CLAUDE.md`](./CLAUDE.md) §3.

## Sécurité

Mode par défaut : **paper trading**. Bascule en capital réel interdite sans la checklist `docs/go-live-checklist.md` (phase 14).

**Kill switch** actif via l'une des trois sources indépendantes (INV-2) :

1. `KILL_SWITCH=1` dans l'environnement
2. `POST /kill-switch` (backend + pub/sub Redis)
3. Bouton rouge dans l'UI (header permanent)

Ne jamais désactiver le risk manager, ne jamais committer `.env`, ne jamais importer les SDK broker/social/LLM hors de `backend/providers/` (INV-5 + règle lint phase 4).

## Tests

```bash
uv run pytest                  # suite complète
uv run pytest tests/unit       # unitaires
uv run pytest --cov=backend    # couverture
```

Seuils obligatoires une fois le risk manager implémenté (phase 6) :
- Global ≥ 80 %
- `backend/risk/` = 100 % (INV-3)

## Contribuer

- Branches : `feat/<ticket-id>-slug`, `fix/...`, `chore/...`.
- Commits : [Conventional Commits](https://www.conventionalcommits.org/).
- PR : le template `.github/pull_request_template.md` impose la checklist INV-1 à INV-7.
