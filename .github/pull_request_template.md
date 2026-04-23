## Objectif

<!-- 1-2 phrases -->

## Ticket BACKLOG

- [ ] Lien : `<EPIC-NN>`

## Invariants (CLAUDE.md §2)

Cocher chaque invariant **pertinent** pour ce PR après vérification effective. Les invariants non touchés restent cochés « n/a ».

- [ ] **INV-1** — Double opt-in live trading respecté (`TRADING_MODE`, `PAPER_TRADING`, kill switch).
- [ ] **INV-2** — Kill switch reste opérationnel sur les 3 canaux (env, endpoint, UI).
- [ ] **INV-3** — Aucun chemin n'atteint `broker.place_order` sans `risk_manager.validate`.
- [ ] **INV-4** — Tables d'audit restent append-only ; aucune migration destructive.
- [ ] **INV-5** — Aucun secret logué ou committé ; `StructlogRedactor` appliqué aux nouveaux loggers.
- [ ] **INV-6** — Idempotence préservée (unicité `tweet_id`, `event_id`, `idempotency_key`).
- [ ] **INV-7** — Pas de bascule live sans backtest documenté.

## Tests

- [ ] Unitaires ajoutés / mis à jour.
- [ ] Coverage global ≥ 80 %.
- [ ] Coverage `backend/risk/` = 100 % (si touché).
- [ ] Golden path E2E passe (`pytest tests/e2e -q`, dès phase 9).

## Migrations

- [ ] Alembic ajouté / ajusté si schéma modifié.
- [ ] `alembic upgrade head` puis `downgrade base` vérifiés localement.
- [ ] Aucune action destructive sur tables d'audit (INV-4).

## Observabilité

- [ ] Logs structlog avec `request_id` / `event_id` / `tweet_id` propagés.
- [ ] Métriques Prometheus ajoutées / mises à jour si pertinent.

## Sécurité

- [ ] Aucun `.env` ni secret en clair committé.
- [ ] Pas d'import `ib_insync`, SDK twitterapi.io ou SDK LLM hors de `backend/providers/`.
- [ ] Pas de contournement du risk manager pour « simplifier » les tests.
- [ ] Pas de commande Telegram qui passe un ordre.

## Docs

- [ ] `CLAUDE.md` / `BACKLOG.md` mis à jour si impact architectural.
- [ ] README mis à jour si les commandes de démarrage changent.

## Notes pour le reviewer

<!-- Contexte utile : choix de design, décisions, liens vers issues. -->
