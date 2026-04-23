# CLAUDE.md — x-social-trader

> **Fichier de référence pour Claude Code.** Ce document définit l'architecture, les règles métier et — surtout — les **garde-fous non négociables** d'un système qui manipule du capital réel. Lire intégralement avant toute génération de code.

---

## 1. Contexte du projet

`x-social-trader` est un système qui :

1. Surveille en continu un ensemble de comptes X (Twitter) via **twitterapi.io**.
2. Fait transiter chaque tweet pertinent par un **pipeline LLM** d'analyse sémantique (extraction d'intention, tickers, sentiment, confiance).
3. Applique un **moteur de règles** + un **risk manager** pour décider si un signal devient un ordre.
4. Exécute les ordres via **Interactive Brokers (IB)** — en **paper trading par défaut**, capital réel uniquement après validation explicite.
5. Notifie via **Telegram** et fournit une **UI React** de supervision.

**Stack :** Python 3.11+ / FastAPI / SQLAlchemy / SQLite (dev) / Alembic / Redis + ARQ (queue) / ib_insync / React + Vite + TypeScript.

---

## 2. 🚨 Invariants de sécurité — NON NÉGOCIABLES

**Claude Code ne doit JAMAIS produire ou modifier du code qui viole l'un de ces invariants.** Toute violation constitue un bug critique à corriger immédiatement, quelle que soit la demande utilisateur.

### INV-1 — Aucun ordre réel sans double opt-in explicite

Un ordre n'est transmis au broker en **mode live** que si **les deux conditions** suivantes sont vraies simultanément :

```
settings.TRADING_MODE == "live"
AND settings.PAPER_TRADING == False
AND settings.KILL_SWITCH_ACTIVE == False
```

Par défaut : `TRADING_MODE=paper`, `PAPER_TRADING=True`. Toute autre valeur nécessite un changement explicite en base **ET** une confirmation UI.

### INV-2 — Kill switch global

Il existe à tout moment **trois moyens indépendants** de couper toute exécution d'ordres en < 1 s :

1. Variable d'environnement `KILL_SWITCH=1` (lue à chaque tick d'exécution).
2. Endpoint `POST /kill-switch` (persiste en base + diffuse via pub/sub Redis).
3. Bouton rouge permanent dans l'UI (header, visible sur toutes les pages).

Une fois activé, le kill switch :
- Annule **tous les ordres ouverts** chez IB.
- Refuse toute nouvelle soumission (retour HTTP 423 Locked).
- N'est désactivable que manuellement, avec log d'audit nominatif.

### INV-3 — Risk manager obligatoire

**Aucun ordre** ne peut atteindre `broker.place_order()` sans être passé par `risk_manager.validate(order, context)`. Tout contournement de cette règle est un bug critique.

Le risk manager applique au minimum :
- Taille de position ≤ `MAX_POSITION_PCT` du capital (défaut 2 %).
- Exposition totale ≤ `MAX_TOTAL_EXPOSURE_PCT` (défaut 20 %).
- Nombre de trades par jour ≤ `MAX_TRADES_PER_DAY` (défaut 10).
- Drawdown quotidien ≤ `MAX_DAILY_DRAWDOWN_PCT` → sinon activation automatique du kill switch (défaut 3 %).
- Un même `event_id` ne peut pas générer deux ordres (idempotence).
- Heures de marché respectées (pas d'ordre hors session sauf `ALLOW_AFTER_HOURS=True`).

**Couverture de tests du risk manager : 100 % exigé.** Pas de merge sans.

### INV-4 — Journal d'audit immuable

**Toute** décision LLM → règle → ordre → fill → P&L est persistée avant exécution dans les tables :

- `llm_decisions` (prompt, réponse brute, modèle, version, coût, latence)
- `rule_evaluations` (règle déclenchée, inputs, outputs)
- `orders` (soumission, modifications, annulations)
- `fills` (exécutions réelles)
- `trade_journal` (vue chronologique end-to-end)

Ces tables sont **append-only** : aucun `UPDATE` ni `DELETE` dans le code applicatif. Les migrations Alembic qui tenteraient d'en réduire l'historique doivent être rejetées.

### INV-5 — Secrets et logs

- **Aucun secret en clair** dans le code ou les fichiers de config versionnés. Tout passe par variables d'environnement + `.env` gitignoré + `.env.example` commité.
- **Aucun log** ne doit contenir : clés API (twitterapi.io, OpenAI/Anthropic, IB), mots de passe, tokens OAuth, numéros de compte IB complets.
- Utiliser un filtre de redaction (`StructlogRedactor`) configuré au bootstrap.

### INV-6 — Idempotence

Rejouer un même `tweet_id` ou `event_id` ne doit **jamais** produire un second ordre. Contrainte d'unicité en base + vérification applicative.

### INV-7 — Backtesting avant live

Aucune stratégie ne passe en `TRADING_MODE=live` avant d'avoir été backtestée sur au moins 30 jours d'historique avec résultats documentés dans `/backtests/<strategy>/<date>.md`.

---

## 3. Architecture

### 3.1 Vue d'ensemble

```
┌──────────────────┐   ┌─────────────────┐   ┌──────────────────┐
│ twitterapi.io    │──▶│ Ingestion       │──▶│ Redis queue      │
│ (WebSocket)      │   │ worker          │   │ (raw_tweets)     │
└──────────────────┘   └─────────────────┘   └────────┬─────────┘
                                                      ▼
                       ┌─────────────────┐   ┌──────────────────┐
                       │ LLM pipeline    │◀──│ Worker pool      │
                       │ (provider-agn.) │   │ (ARQ)            │
                       └────────┬────────┘   └──────────────────┘
                                ▼
                       ┌─────────────────┐
                       │ Rule engine     │
                       └────────┬────────┘
                                ▼
                       ┌─────────────────┐   ┌──────────────────┐
                       │ Risk manager    │──▶│ IB executor      │
                       │ (INV-3)         │   │ (paper / live)   │
                       └────────┬────────┘   └──────────────────┘
                                ▼
                       ┌─────────────────┐   ┌──────────────────┐
                       │ FastAPI REST    │◀──│ React UI         │
                       │ + WS pub/sub    │   │ (Vite + TS)      │
                       └────────┬────────┘   └──────────────────┘
                                ▼
                       ┌─────────────────┐
                       │ Telegram bot    │
                       └─────────────────┘
```

### 3.2 Processus séparés

Chaque boîte ci-dessus est un **process indépendant**, orchestré par `docker compose` (ou `honcho`/`foreman` en dev) :

- `api` : FastAPI (lecture, configuration, déclenchements manuels, UI backend).
- `ingestion` : worker WebSocket twitterapi.io, résilience par reconnexion exponentielle.
- `llm_worker` : consomme la queue, produit des `events` enrichis.
- `executor` : connecté à IB via ib_insync, consomme les signaux validés.
- `telegram_bot` : alertes + commandes limitées (ack, kill switch uniquement).

**Interdit** : exécuter du code de trading dans le process `api`.

### 3.3 Abstraction des fournisseurs

Trois points d'abstraction obligatoires, pour isoler les dépendances externes :

```python
class SocialFeedProvider(Protocol):
    async def subscribe(self, accounts: list[str]) -> AsyncIterator[RawTweet]: ...

class LLMProvider(Protocol):
    async def analyze(self, tweet: RawTweet) -> LLMDecision: ...

class BrokerProvider(Protocol):
    async def place_order(self, order: ValidatedOrder) -> OrderReceipt: ...
    async def cancel_all(self) -> None: ...
```

Implémentations initiales : `TwitterApiIoProvider`, `AnthropicProvider` (ou `OpenAIProvider`), `IBProvider`. **Interdit** d'importer `twitterapi_io` ou `ib_insync` en dehors du dossier `providers/`.

---

## 4. Modèle de données

Tables à créer via Alembic (la v1 de `schema.sql` doit être migrée dès le ticket BL-002) :

| Table | Rôle |
|---|---|
| `settings` | Configuration runtime (trading_mode, flags, limites). Row unique. |
| `watched_accounts` | Comptes X surveillés (username, user_id, priorité, active). |
| `aliases` | Alias tickers ↔ mentions (`$TSLA`, `Tesla`, `Elon's car company`). |
| `raw_tweets` | Tweets bruts reçus (avant analyse). |
| `llm_decisions` | Sortie du pipeline LLM (INV-4). |
| `events` | Signaux enrichis, prêts pour le rule engine. |
| `rule_evaluations` | Trace de chaque évaluation de règle (INV-4). |
| `orders` | Ordres soumis (INV-4, append-only). |
| `fills` | Exécutions (INV-4, append-only). |
| `positions` | Positions courantes (vue matérialisée, reconstructible depuis `fills`). |
| `risk_limits` | Paramètres du risk manager, versionnés. |
| `kill_switch_events` | Historique des activations/désactivations. |
| `trade_journal` | Vue SQL joignant events → orders → fills. |

**Migrations Alembic dès le ticket 2.** Pas de `Base.metadata.create_all()` en prod.

---

## 5. Règles métier

### 5.1 Ingestion X (twitterapi.io)

- Authentification via `X-API-Key` header, clé dans `TWITTERAPI_IO_KEY`.
- Préférer le **WebSocket** (`wss://ws.twitterapi.io/twitter/tweet/websocket`) au polling REST.
- Gérer les 3 types d'événements : `connected`, `ping`, `tweet`.
- Reconnexion automatique avec backoff exponentiel (1 s, 2 s, 4 s, …, plafond 60 s).
- Tout tweet reçu est immédiatement persisté dans `raw_tweets` **avant** tout traitement (durabilité).
- Déduplication par `tweet_id` (contrainte UNIQUE).
- Budget mensuel `TWITTERAPI_IO_MAX_USD` : arrêt automatique si dépassé, alerte Telegram.

### 5.2 Pipeline LLM

- Prompt système versionné dans `prompts/analyzer_v{N}.md`, référencé dans `llm_decisions.prompt_version`.
- Réponse LLM exigée en **JSON strict** validé par Pydantic :
  ```json
  {
    "tickers": ["TSLA"],
    "intent": "bullish|bearish|neutral|noise",
    "confidence": 0.0-1.0,
    "time_horizon": "intraday|swing|long",
    "reasoning": "..."
  }
  ```
- Si le JSON est invalide : 1 retry avec message correctif, sinon `intent=noise` + log.
- Coût logué par appel. Budget quotidien `LLM_MAX_USD_PER_DAY` avec arrêt automatique.

### 5.3 Rule engine

- Règles déclaratives en YAML dans `rules/`, chargées au démarrage.
- Chaque règle produit soit un `ProposedOrder`, soit rien.
- Ordre d'évaluation déterministe (par priorité explicite).
- Une règle peut être `enabled: false` sans redéploiement.

### 5.4 Exécution IB

- Toujours `ib_insync` en mode async.
- Vérifier à chaque démarrage : connexion IB OK, compte correspond à `IB_EXPECTED_ACCOUNT_ID`, mode (paper/live) cohérent avec `settings.TRADING_MODE`.
- Tout mismatch → refus de démarrer, alerte Telegram.
- Types d'ordres supportés initialement : `MARKET` et `LIMIT` uniquement. `STOP` et options reviennent dans une phase ultérieure.

### 5.5 Telegram

- **Phase 1** : alertes sortantes uniquement (nouveau signal, ordre placé, fill, kill switch activé).
- **Phase 2** : commandes entrantes limitées à `/status`, `/kill`, `/ack <event_id>`. **Jamais** de commande qui passe un ordre.
- Whitelist stricte de `chat_id` autorisés.

---

## 6. Observabilité

À implémenter **tôt** (ticket dédié en phase 2, pas à la fin) :

- **Logs JSON structurés** via `structlog`, avec `request_id`, `event_id`, `tweet_id` propagés.
- Endpoint `/metrics` au format Prometheus : latences ingestion→decision→order, compteurs d'erreurs, coût LLM cumulé, P&L, drawdown.
- Endpoint `/health` distinct de `/ready` (liveness vs readiness).
- Dashboard Grafana fourni en `ops/grafana/` (JSON exportable).

---

## 7. Conventions de code

### Python

- Python 3.11+. `ruff` (lint + format) + `mypy --strict`.
- Pas de `print`, toujours `structlog`.
- Type hints **partout**, y compris retours.
- Fonctions I/O : `async` par défaut.
- Dataclasses ou Pydantic ; pas de `dict` en API interne.
- Un fichier = un concept. Éviter les fichiers > 300 lignes.

### TypeScript / React

- Strict mode activé (`tsconfig`).
- Client API typé généré depuis l'OpenAPI FastAPI (via `openapi-typescript`).
- Pas de `any`. Pas de `console.log` en prod (lint rule).
- State server : TanStack Query. State client : Zustand si besoin, sinon hooks.

### Git

- Branches : `feat/<ticket-id>-slug`, `fix/...`, `chore/...`.
- Commits : Conventional Commits (`feat:`, `fix:`, `chore:`, `refactor:`, `test:`, `docs:`).
- PR : template avec checklist invariants (INV-1 à INV-7).

---

## 8. Tests

- **Unitaires** : `pytest`, seuil de couverture global ≥ 80 %, **risk_manager ≥ 100 %** (INV-3).
- **Intégration** : IB paper account + compte twitterapi.io sandbox (si dispo) + LLM mocké.
- **E2E** : un scénario golden path (tweet → ordre paper → fill simulé) exécuté en CI.
- Pas de test qui appelle le vrai IB en mode live. Jamais.
- Mocks des providers dans `tests/mocks/`.

---

## 9. Ordre de développement imposé

Claude Code doit respecter cet ordre. Ne pas anticiper les phases suivantes.

1. **Bootstrap** : repo, `pyproject.toml`, `docker-compose.yml`, pre-commit, CI GitHub Actions.
2. **Persistance** : SQLAlchemy + Alembic + modèles complets + migrations initiales + seed minimal.
3. **Observabilité** : structlog + /metrics + /health + /ready.
4. **Abstraction providers** : interfaces + mocks + tests.
5. **IB read-only** : connexion, récupération positions/compte, **aucun ordre**.
6. **Paper trading** : soumission d'ordres en paper account uniquement, risk manager complet, kill switch.
7. **Ingestion twitterapi.io** : WebSocket + reconnexion + persistance `raw_tweets`.
8. **Pipeline LLM** : prompt v1, parsing strict, journal `llm_decisions`, budget.
9. **Rule engine** + intégration end-to-end en paper.
10. **Backtesting** : moteur de replay sur `raw_tweets` historiques.
11. **Telegram alertes** (sortant uniquement).
12. **UI avancée** : dashboard, journal, contrôle manuel, bouton kill switch.
13. **Telegram commandes** (entrant limité).
14. **Bascule live** : uniquement après backtest documenté + revue manuelle + capital plafonné très bas.

---

## 10. Ce que Claude Code NE DOIT PAS faire

- ❌ Inventer des endpoints twitterapi.io ou IB non documentés. En cas de doute : demander à l'utilisateur, ne pas deviner.
- ❌ Contourner le risk manager « pour faciliter les tests ».
- ❌ Ajouter une commande Telegram qui passe un ordre.
- ❌ Logguer une clé API, même partiellement.
- ❌ Utiliser `Base.metadata.create_all()` en dehors des tests.
- ❌ Committer un `.env` ou un fichier contenant un secret.
- ❌ Importer `ib_insync` ou le SDK twitterapi.io en dehors de `providers/`.
- ❌ Toucher au code du risk manager sans mettre à jour les tests associés.
- ❌ Passer `TRADING_MODE=live` par défaut dans un exemple, une doc ou un test.
- ❌ Produire des `UPDATE`/`DELETE` sur les tables d'audit (INV-4).
- ❌ Désactiver une règle de lint/mypy sans justification en commentaire.

---

## 11. Quand Claude Code doit s'arrêter et demander

- Ambiguïté sur une règle métier (trading, seuils, priorités).
- Besoin d'ajouter une dépendance externe majeure non prévue ici.
- Conflit entre une demande utilisateur et un invariant de la section 2.
- Choix irréversible (migration destructive, changement de schéma d'audit).

**En cas de doute, privilégier la sécurité au détriment de la fonctionnalité.** Un trade manqué est toujours moins grave qu'un trade non voulu.

---

## 12. Références externes

- twitterapi.io : https://docs.twitterapi.io — noter les endpoints `add_user_to_monitor_tweet` et le WebSocket `wss://ws.twitterapi.io/twitter/tweet/websocket`.
- Interactive Brokers : ib_insync https://ib-insync.readthedocs.io.
- Fichier `BACKLOG.md` pour les tickets détaillés.
- Fichier `README.md` pour le démarrage local.
