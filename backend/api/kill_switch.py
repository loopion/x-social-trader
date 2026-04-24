"""Kill switch HTTP endpoints (KILL-02 + KILL-03)."""

from __future__ import annotations

from typing import Annotated

from fastapi import APIRouter, Depends, Header, HTTPException, status
from sqlalchemy.ext.asyncio import AsyncSession

from backend.core.settings import Settings, get_settings
from backend.db.session import get_session
from backend.kill_switch import KillSwitchService, build_kill_switch_service
from backend.models.enums import KillSwitchTrigger

router = APIRouter(prefix="/kill-switch", tags=["kill-switch"])


async def get_kill_switch_service(
    session: Annotated[AsyncSession, Depends(get_session)],
    settings: Annotated[Settings, Depends(get_settings)],
) -> KillSwitchService:
    return build_kill_switch_service(session=session, redis_url=settings.redis_url)


SessionDep = Annotated[AsyncSession, Depends(get_session)]
ServiceDep = Annotated[KillSwitchService, Depends(get_kill_switch_service)]


@router.get("")
async def status_(service: ServiceDep) -> dict[str, str | bool]:
    state = await service.is_active()
    return {"active": state.active, "source": state.source}


@router.post("", status_code=status.HTTP_200_OK)
async def activate(
    service: ServiceDep,
    session: SessionDep,
    x_actor: Annotated[str, Header(alias="X-Actor")] = "anonymous",
    reason: Annotated[str | None, Header(alias="X-Reason")] = None,
) -> dict[str, str | bool | int]:
    """Manual activation. INV-2 — one of three independent paths.

    `X-Actor` header identifies the caller for the audit log (defaults to
    ``anonymous``; proper auth arrives in a later phase).
    """
    event = await service.activate(
        trigger=KillSwitchTrigger.MANUAL,
        actor=x_actor,
        reason=reason,
    )
    await session.commit()
    return {"active": True, "source": "db", "event_id": event.id}


@router.post("/deactivate", status_code=status.HTTP_200_OK)
async def deactivate(
    service: ServiceDep,
    session: SessionDep,
    x_confirm: Annotated[str | None, Header(alias="X-Confirm")] = None,
    x_actor: Annotated[str, Header(alias="X-Actor")] = "anonymous",
    reason: Annotated[str, Header(alias="X-Reason")] = "",
) -> dict[str, str | bool | int]:
    """KILL-03 — deactivation requires ``X-Confirm: I-understand`` + audit trail."""
    if x_confirm != "I-understand":
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Deactivation requires header `X-Confirm: I-understand`",
        )
    if not reason:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Deactivation requires a non-empty `X-Reason` header",
        )
    event = await service.deactivate(actor=x_actor, reason=reason)
    await session.commit()
    return {"active": False, "source": "db", "event_id": event.id}
