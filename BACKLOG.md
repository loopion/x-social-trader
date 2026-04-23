# BACKLOG.md — x-social-trader

> Backlog structuré par epics, tickets, sous-tâches et critères d'acceptation (CA). À lire avec `CLAUDE.md` — les invariants INV-1 à INV-7 s'appliquent à **chaque** ticket.
>
> **Convention d'ID** : `<EPIC>-<NN>` (ex. `BOOT-01`). Les phases doivent être traitées dans l'ordre. Ne pas démarrer une phase N+1 tant que les tickets « must » de la phase N ne sont pas verts.
>
> **Priorité** : `must` (bloquant) / `should` (important) / `could` (nice-to-have).

---

## Phase 1 — Bootstrap

### Epic BOOT — Mise en place du repo et de la CI

#### BOOT-01 — Structure du monorepo (`must`)

**Objectif** : squelette reproductible avec tooling standardisé.

- [ ] Arborescence : `backend/`, `frontend/`, `ops/`, `prompts/`, `rules/`, `backtests/`, `docs/`.
- [ ] `pyproject.toml` (uv ou poetry) avec groupes `dev`, `test`.
- [ ] `ruff` (lint + format) + `mypy --strict` + `pytest` configurés.
- [ ] `pre-commit` avec hooks ruff, mypy, detect-secrets, check-yaml.
- [ ] `.env.example` listant **toutes** les variables (sans valeurs).
- [ ] `.gitignore` strict : `.env`, `*.db`, `__pycache__`, `node_modules`, `dist`.
- [ ] `README.md` avec démarrage local en <10 min.

**CA** :
- `pre-commit run --all-files` passe sur repo vierge.
- `ruff check .` et `mypy backend/` retournent 0 erreur.
- `detect-secrets` ne remonte aucun faux positif.

#### BOOT-02 — CI GitHub Actions (`must`)

- [ ] Job `lint` : ruff + mypy.
- [ ] Job `test-backend` : pytest + coverage, seuil global 80 %, **risk_manager 100 %** (INV-3).
- [ ] Job `test-frontend` : vitest + tsc --noEmit.
- [ ] Job `secrets-scan` : detect-secrets.
- [ ] Artefacts : rapport coverage.

**CA** : une PR qui casse l'un des seuils est bloquée en merge.

#### BOOT-03 — Docker Compose dev (`must`)

- [ ] Services : `api`, `ingestion`, `llm_worker`, `executor`, `telegram_bot`, `redis`, `frontend`.
- [ ] Réseau unique, volumes pour SQLite et logs.
- [ ] `docker compose up` démarre l'ensemble sans erreur (services en stub si dépendances externes absentes).
- [ ] Healthchecks par service.

**CA** : `docker compose up` → `/health` répond 200 en <30 s.

#### BOOT-04 — Template de PR (`should`)

- [ ] `.github/pull_request_template.md` avec checklist INV-1 à INV-7, tests, migrations.

---

## Phase 2 — Persistance

### Epic DB — Base de données et migrations

#### DB-01 — Configuration SQLAlchemy async (`must`)

- [ ] Engine async (`aiosqlite` en dev, driver Postgres prêt).
- [ ] Session factory avec dépendance FastAPI.
- [ ] Pas de `Base.metadata.create_all()` hors tests.

**CA** : import circulaire-free, pas de session fuitée entre requêtes.

#### DB-02 — Modèles initiaux (`must`)

Tables (cf. CLAUDE.md §4) : `settings`, `watched_accounts`, `aliases`, `raw_tweets`, `llm_decisions`, `events`, `rule_evaluations`, `orders`, `fills`, `positions`, `risk_limits`, `kill_switch_events`.

- [ ] Un fichier par table dans `backend/models/`.
- [ ] Contraintes UNIQUE sur `raw_tweets.tweet_id`, `orders.idempotency_key`, `events.event_id` (INV-6).
- [ ] Tables d'audit : pas de colonne `updated_at` modifiable (INV-4).
- [ ] Index sur colonnes de recherche fréquente (`created_at`, `tweet_id`, `ticker`).

**CA** : schéma cohérent avec §4 de CLAUDE.md, checklist revue.

#### DB-03 — Alembic (`must`)

- [ ] Init Alembic avec env async.
- [ ] Migration `0001_initial` reproduisant DB-02.
- [ ] Script `make migrate` / `make migrate-new`.
- [ ] CI : `alembic upgrade head` puis `alembic downgrade base` passent.

**CA** : un checkout propre + migrate → base utilisable.

#### DB-04 — Protection append-only des tables d'audit (`must`)

- [ ] Triggers SQLite `BEFORE UPDATE/DELETE` sur `llm_decisions`, `orders`, `fills`, `rule_evaluations`, `kill_switch_events` → rejet (`RAISE ABORT`).
- [ ] Test vérifiant qu'un UPDATE/DELETE lève une exception.

**CA** : tentative de modification en test = erreur SQL.

#### DB-05 — Seed minimal (`should`)

- [ ] Script `scripts/seed.py` : 1 row `settings` par défaut (paper mode), 2-3 `watched_accounts` de démo, quelques `aliases`.
- [ ] Idempotent.

---

## Phase 3 — Observabilité

### Epic OBS — Logs, métriques, health

#### OBS-01 — Logs structurés (`must`)

- [ ] `structlog` configuré JSON en prod, console-pretty en dev.
- [ ] Contexte propagé : `request_id`, `event_id`, `tweet_id`, `order_id`.
- [ ] `StructlogRedactor` filtre les clés sensibles (INV-5) : patterns pour API keys, tokens, numéros de compte.
- [ ] Test : un log volontaire contenant une fausse clé API apparaît rédacté.

**CA** : grep sur la sortie JSON ne retrouve jamais de secret en clair.

#### OBS-02 — Endpoints santé (`must`)

- [ ] `/health` : liveness (process vivant).
- [ ] `/ready` : readiness (DB OK, Redis OK, IB connecté si exécutor).
- [ ] Distinction utilisée par Docker healthchecks.

**CA** : `/ready` renvoie 503 si une dépendance est down.

#### OBS-03 — Métriques Prometheus (`must`)

- [ ] Endpoint `/metrics`.
- [ ] Compteurs : `tweets_ingested_total`, `llm_calls_total{status}`, `orders_submitted_total{mode}`, `kill_switch_activations_total`.
- [ ] Histogrammes : latence `ingestion→decision`, `decision→order`, latence LLM, latence broker.
- [ ] Gauges : `llm_cost_usd_daily`, `pnl_daily_usd`, `drawdown_pct`, `open_positions`.

**CA** : `curl /metrics` retourne tous les compteurs listés.

#### OBS-04 — Dashboard Grafana (`should`)

- [ ] `ops/grafana/x-social-trader.json` importable.
- [ ] Panneaux : flux ingestion, coût LLM, ordres, P&L, drawdown, activations kill switch.

---

## Phase 4 — Abstractions providers

### Epic PROV — Interfaces et mocks

#### PROV-01 — Protocoles (`must`)

- [ ] `backend/providers/base.py` : `SocialFeedProvider`, `LLMProvider`, `BrokerProvider` (cf. CLAUDE.md §3.3).
- [ ] Modèles Pydantic : `RawTweet`, `LLMDecision`, `ValidatedOrder`, `OrderReceipt`, `Fill`.
- [ ] Règle lint/import : interdit d'importer `ib_insync`, clients twitterapi.io ou SDK LLM hors de `providers/`.

**CA** : `import-linter` ou équivalent fait échouer une PR qui viole la règle.

#### PROV-02 — Mocks pour tests (`must`)

- [ ] `tests/mocks/social.py` : `MockSocialFeedProvider` avec scénarios scriptés.
- [ ] `tests/mocks/llm.py` : réponses déterministes par `tweet_id`.
- [ ] `tests/mocks/broker.py` : simulateur d'ordres (fills instantanés ou différés).

**CA** : un test E2E tourne entièrement sur les mocks sans accès réseau.

---

## Phase 5 — IB read-only

### Epic IB — Intégration Interactive Brokers

#### IB-01 — Connexion ib_insync (`must`)

- [ ] `IBProvider.connect()` avec retry + timeout.
- [ ] Vérification au démarrage : `account_id == IB_EXPECTED_ACCOUNT_ID`, mode paper/live cohérent avec `settings.TRADING_MODE`.
- [ ] Tout mismatch → refus de démarrer, log critique, alerte (manuelle à ce stade).

**CA** : démarrage avec mauvais account → process exit code non-0, log explicite.

#### IB-02 — Lecture compte et positions (`must`)

- [ ] `get_account_summary()`, `get_positions()`, `get_open_orders()`.
- [ ] Synchronisation périodique vers table `positions` (reconstructible depuis `fills`).
- [ ] **Aucune** méthode `place_order` exposée à ce stade.

**CA** : UI peut afficher positions réelles du paper account, rien d'autre.

#### IB-03 — Tests d'intégration IB paper (`should`)

- [ ] Suite optionnelle (skip si pas de `IB_GATEWAY_URL`) validant lecture réelle.
- [ ] Exécutée manuellement, pas en CI par défaut.

---

## Phase 6 — Paper trading, Risk Manager, Kill Switch

### Epic RISK — Risk manager (INV-3, couverture 100 %)

#### RISK-01 — Règles de validation (`must`)

- [ ] `risk_manager.validate(order, context) -> ValidationResult`.
- [ ] Règles : `MAX_POSITION_PCT`, `MAX_TOTAL_EXPOSURE_PCT`, `MAX_TRADES_PER_DAY`, `MAX_DAILY_DRAWDOWN_PCT`, heures de marché, idempotence.
- [ ] Chaque règle = classe indépendante avec `check(order, context) -> RuleOutcome`.
- [ ] Résultat = liste d'échecs (pas court-circuit au premier).

**CA** :
- Coverage 100 % sur `backend/risk/`.
- Chaque règle a un test négatif et un test positif.
- Un test vérifie qu'on ne peut pas construire un `ValidatedOrder` sans passer par `validate()`.

#### RISK-02 — Persistance des évaluations (`must`)

- [ ] Chaque appel `validate()` écrit dans `rule_evaluations` (INV-4).
- [ ] Inclut : inputs hashés, règles évaluées, outcome, timestamp.

**CA** : rejeu d'un event via journal retrouve la décision d'origine.

### Epic KILL — Kill switch (INV-2)

#### KILL-01 — Source de vérité (`must`)

- [ ] Table `kill_switch_events` (append-only) + cache Redis.
- [ ] Fonction `is_active() -> bool` vérifie (dans l'ordre) : env var `KILL_SWITCH=1`, Redis `kill_switch:active`, dernière row DB.
- [ ] Latence de lecture < 5 ms.

**CA** : test de bascule (off→on) propagée aux 3 sources en <1 s.

#### KILL-02 — Endpoint et pub/sub (`must`)

- [ ] `POST /kill-switch` (auth requise) : persiste + publie sur canal Redis `kill_switch`.
- [ ] `executor` abonné → annule tous ordres ouverts via `broker.cancel_all()`, refuse nouvelles soumissions.
- [ ] Réponse HTTP 423 Locked sur toute tentative d'ordre pendant kill switch actif.

**CA** : test E2E : activation → ordre pending annulé + nouvelle soumission refusée.

#### KILL-03 — Désactivation (`must`)

- [ ] `POST /kill-switch/deactivate` nécessite confirmation explicite (header `X-Confirm: I-understand`).
- [ ] Log d'audit nominatif (utilisateur, timestamp, raison).

**CA** : désactivation sans header → 400.

#### KILL-04 — Bouton UI permanent (`must`)

- [ ] Composant `<KillSwitchButton />` visible dans le header de **toutes** les pages.
- [ ] Rouge quand inactif (cliquable), clignotant quand actif.
- [ ] Confirmation modale avant activation.

**CA** : review manuelle de 3 pages différentes confirme la présence.

#### KILL-05 — Drawdown → kill switch auto (`must`)

- [ ] Worker périodique calcule drawdown jour.
- [ ] Dépassement `MAX_DAILY_DRAWDOWN_PCT` → activation automatique + alerte.

**CA** : test simulant P&L négatif déclenche l'activation.

### Epic EXEC — Exécuteur paper

#### EXEC-01 — Soumission d'ordres paper (`must`)

- [ ] Méthode `place_order` chez `IBProvider` active mais **gated** par INV-1.
- [ ] Vérification en début de méthode : `settings.TRADING_MODE`, `PAPER_TRADING`, `is_kill_switch_active()`, `risk_manager.validate()`.
- [ ] Persistance `orders` avant appel broker, `fills` sur callback.

**CA** : test : tentative live avec `TRADING_MODE=paper` → `PermissionError` claire.

#### EXEC-02 — Idempotence (`must`)

- [ ] `idempotency_key = hash(event_id + strategy_id)`.
- [ ] Contrainte UNIQUE + vérification applicative.

**CA** : rejeu du même event → second appel retourne l'ordre original sans doublon.

#### EXEC-03 — Reconstruction positions (`should`)

- [ ] Worker périodique reconstruit `positions` depuis `fills`.
- [ ] Réconciliation avec IB toutes les 5 min, log si divergence.

---

## Phase 7 — Ingestion twitterapi.io

### Epic ING — Ingestion temps réel

#### ING-01 — Client HTTP (`must`)

- [ ] `TwitterApiIoClient` : auth via header `X-API-Key`, lu depuis `TWITTERAPI_IO_KEY`.
- [ ] Méthodes : `add_user_to_monitor`, `remove_user_to_monitor`, `list_monitored_users`, `advanced_search` (backfill).
- [ ] Retry exponentiel sur 5xx, pas de retry sur 4xx.

**CA** : tests contract avec réponses mockées (fixtures JSON réelles).

#### ING-02 — WebSocket stream (`must`)

- [ ] Connexion à `wss://ws.twitterapi.io/twitter/tweet/websocket`.
- [ ] Gestion des 3 événements : `connected`, `ping`, `tweet`.
- [ ] Reconnexion exponentielle 1→60 s sur déconnexion.
- [ ] Persistance `raw_tweets` **avant** toute transformation (durabilité).
- [ ] Déduplication via `UNIQUE(tweet_id)`.

**CA** : simulation de coupure réseau → reprise automatique, 0 tweet perdu sur replay.

#### ING-03 — Synchronisation watched_accounts (`must`)

- [ ] Au démarrage : compare `watched_accounts` DB avec monitoring twitterapi.io, aligne.
- [ ] Changement UI → appel `add/remove` côté twitterapi.io.
- [ ] Budget mensuel `TWITTERAPI_IO_MAX_USD` : arrêt si dépassé, alerte.

**CA** : toggle d'un compte en UI reflète sur la liste remote en <5 s.

#### ING-04 — Publication vers queue (`must`)

- [ ] Après persistance, push vers Redis queue `raw_tweets` (ARQ).
- [ ] Backpressure : si queue > seuil, log warning + métrique.

---

## Phase 8 — Pipeline LLM

### Epic LLM — Analyse sémantique

#### LLM-01 — Prompt v1 versionné (`must`)

- [ ] `prompts/analyzer_v1.md` avec instructions + schéma JSON attendu.
- [ ] `prompt_version` stocké dans chaque `llm_decisions`.

#### LLM-02 — Worker analyzer (`must`)

- [ ] Consomme queue `raw_tweets`, appelle `LLMProvider.analyze()`.
- [ ] Parsing Pydantic strict du JSON de sortie.
- [ ] Sur JSON invalide : 1 retry avec message correctif, sinon `intent=noise`.
- [ ] Persistance `llm_decisions` (prompt, réponse brute, modèle, coût, latence).
- [ ] Push vers queue `events` si `intent != noise`.

**CA** : 100 tweets fixtures → 0 crash, tous persistés.

#### LLM-03 — Budget et alerting (`must`)

- [ ] Compteur coût journalier persistant.
- [ ] Dépassement `LLM_MAX_USD_PER_DAY` → arrêt worker, alerte Telegram, métrique.

**CA** : test simulant budget dépassé → worker refuse nouveaux appels.

#### LLM-04 — Résolution tickers via aliases (`should`)

- [ ] Post-traitement : mapping mentions → tickers via `aliases`.
- [ ] Ambiguïté (`Apple` → AAPL ou fruit ?) → contexte LLM explicite.

---

## Phase 9 — Rule engine et intégration end-to-end paper

### Epic RULE — Moteur de règles

#### RULE-01 — Format YAML et chargement (`must`)

- [ ] Schéma YAML dans `rules/`, validé Pydantic au chargement.
- [ ] Champs : `id`, `priority`, `enabled`, `conditions`, `action` (order template).

#### RULE-02 — Évaluation déterministe (`must`)

- [ ] Tri par `priority`, évaluation jusqu'au premier match (ou tous, selon stratégie).
- [ ] Persistance `rule_evaluations` pour chaque règle évaluée.

#### RULE-03 — Hot-reload (`should`)

- [ ] Endpoint admin pour recharger les règles sans redémarrer.

#### RULE-04 — E2E paper golden path (`must`)

- [ ] Scénario CI : tweet fixture → LLM mock → règle match → ordre paper → fill simulé → `trade_journal` cohérent.

**CA** : test CI vert, durée <30 s.

---

## Phase 10 — Backtesting

### Epic BT — Moteur de backtest

#### BT-01 — Replay sur raw_tweets (`must`)

- [ ] CLI `python -m backtests.run --strategy=<id> --from=<date> --to=<date>`.
- [ ] Rejoue LLM (cache décisions si possible) + rule engine + exécution simulée avec prix historiques.

#### BT-02 — Rapports (`must`)

- [ ] Sortie : `backtests/<strategy>/<date>.md` avec métriques (P&L, Sharpe, max drawdown, nb trades, win rate).
- [ ] Graphique equity curve.

**CA** : BT-01 produit rapport reproductible.

#### BT-03 — Gate de passage en live (`must`)

- [ ] Script `scripts/check_live_readiness.py` : refuse la bascule live si aucun rapport récent (<30j) pour la stratégie.

---

## Phase 11 — Telegram alertes

### Epic TG — Bot Telegram (sortant)

#### TG-01 — Bot et whitelist (`must`)

- [ ] `python-telegram-bot` ou équivalent async.
- [ ] Whitelist `TELEGRAM_ALLOWED_CHAT_IDS` stricte.

#### TG-02 — Alertes sortantes (`must`)

- [ ] Événements notifiés : nouveau signal, ordre soumis, fill, kill switch, budget LLM/twitterapi dépassé, drawdown déclenché.
- [ ] Formatage markdown concis + lien UI.

**CA** : chaque événement simulé produit une alerte formatée.

---

## Phase 12 — UI avancée

### Epic UI — Dashboard React

#### UI-01 — Client API typé (`must`)

- [ ] Génération via `openapi-typescript` depuis `/openapi.json`.
- [ ] TanStack Query pour fetch/cache.

#### UI-02 — Pages (`must`)

- [ ] `Dashboard` : P&L, positions, flux tweets live, drawdown.
- [ ] `Journal` : `trade_journal` paginé + filtres.
- [ ] `Accounts` : gestion `watched_accounts`.
- [ ] `Aliases` : CRUD.
- [ ] `Rules` : lecture + toggle enabled.
- [ ] `Settings` : limites, budgets, mode trading (avec garde-fous visuels).
- [ ] `KillSwitch` bouton global header (KILL-04).

#### UI-03 — WebSocket live feed (`should`)

- [ ] Canal WS backend pour push tweets / ordres en temps réel vers UI.

---

## Phase 13 — Telegram commandes entrantes

### Epic TGI — Commandes limitées (INV)

#### TGI-01 — Commandes autorisées uniquement (`must`)

- [ ] `/status`, `/kill`, `/ack <event_id>`.
- [ ] **Jamais** de commande qui passe un ordre.
- [ ] Confirmation pour `/kill` (message interactif).

**CA** : review code confirme absence d'appel à `broker.place_order` depuis le bot.

---

## Phase 14 — Bascule live

### Epic LIVE — Passage capital réel

#### LIVE-01 — Checklist pré-bascule (`must`)

Document `docs/go-live-checklist.md` listant :
- Backtest récent vert (BT-03).
- Coverage tests OK.
- Kill switch testé manuellement <7j.
- Plafond capital `MAX_CAPITAL_USD` défini et très bas.
- Revue manuelle par utilisateur.

#### LIVE-02 — Flag de bascule (`must`)

- [ ] Commande CLI `scripts/go_live.py` qui exige confirmation texte exacte + modifie `settings`.
- [ ] Refus si checklist LIVE-01 pas validée (fichier signé).

**CA** : tentative sans checklist → refus + log.

---

## Annexes

### Variables d'environnement (à compléter dans `.env.example`)

```
# Trading
TRADING_MODE=paper
PAPER_TRADING=true
KILL_SWITCH=0
MAX_CAPITAL_USD=1000
MAX_POSITION_PCT=2
MAX_TOTAL_EXPOSURE_PCT=20
MAX_TRADES_PER_DAY=10
MAX_DAILY_DRAWDOWN_PCT=3
ALLOW_AFTER_HOURS=false

# IB
IB_GATEWAY_URL=...
IB_EXPECTED_ACCOUNT_ID=...

# twitterapi.io
TWITTERAPI_IO_KEY=...
TWITTERAPI_IO_MAX_USD=50

# LLM
LLM_PROVIDER=anthropic
LLM_API_KEY=...
LLM_MAX_USD_PER_DAY=5

# Telegram
TELEGRAM_BOT_TOKEN=...
TELEGRAM_ALLOWED_CHAT_IDS=...

# Infra
DATABASE_URL=sqlite+aiosqlite:///./data/app.db
REDIS_URL=redis://redis:6379/0
```

### Checklist de PR (à coller dans chaque PR)

- [ ] Respecte INV-1 à INV-7 (cf. CLAUDE.md §2).
- [ ] Tests ajoutés / mis à jour.
- [ ] Coverage global ≥ 80 %, risk_manager 100 %.
- [ ] Migration Alembic si schéma modifié.
- [ ] Aucun secret commité.
- [ ] Pas d'import de SDK externe hors `providers/`.
- [ ] Logs ne contiennent pas d'info sensible.
- [ ] Docs mises à jour si API publique changée.
