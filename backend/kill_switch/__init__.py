"""Kill switch (INV-2) — three independent activation paths + audit log.

Sources of truth, in priority order:
1. ``KILL_SWITCH=1`` env var — highest priority, overrides everything.
2. Redis key ``kill_switch:active`` — fast distributed cache, published to
   subscribers via the ``kill_switch`` channel whenever state changes.
3. ``kill_switch_events`` table (append-only, INV-4) — canonical history.

`KillSwitchService.is_active()` must reflect activation in under 1 s.
"""

from backend.kill_switch.service import (
    KillSwitchService,
    KillSwitchState,
    build_kill_switch_service,
)

__all__ = [
    "KillSwitchService",
    "KillSwitchState",
    "build_kill_switch_service",
]
