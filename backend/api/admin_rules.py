"""Admin rule endpoints — RULE-03 hot reload + introspection.

The endpoints are intentionally unauthenticated for now (auth lands in
a later phase); they are operationally-equivalent to a SIGHUP and the
``GET`` is read-only. ``POST /admin/rules/reload`` re-reads ``rules/``
from disk and atomically swaps the in-memory store.
"""

from __future__ import annotations

from typing import Annotated, Any

from fastapi import APIRouter, Depends, HTTPException, Request, status

from backend.rules.loader import RuleLoadError
from backend.rules.store import RuleStore

router = APIRouter(prefix="/admin/rules", tags=["admin", "rules"])


def get_rule_store(request: Request) -> RuleStore:
    store = getattr(request.app.state, "rule_store", None)
    if store is None:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="rule store not initialised",
        )
    if not isinstance(store, RuleStore):
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="app.state.rule_store has unexpected type",
        )
    return store


StoreDep = Annotated[RuleStore, Depends(get_rule_store)]


@router.get("")
def list_rules(store: StoreDep) -> dict[str, Any]:
    rules = store.get_rules()
    return {
        "directory": str(store.directory),
        "count": len(rules),
        "rules": [
            {
                "id": r.id,
                "priority": r.priority,
                "enabled": r.enabled,
                "description": r.description,
            }
            for r in rules
        ],
    }


@router.post("/reload")
def reload_rules(store: StoreDep) -> dict[str, Any]:
    try:
        count = store.reload()
    except RuleLoadError as exc:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=str(exc)) from exc
    return {"loaded": count, "directory": str(store.directory)}
