"""Process-wide maintenance flag + pre-maintenance schedule.

`_active` is flipped on by destructive operations (backup restore in v0.13.0,
nightly sweeps once their job is claimed in v0.14.0+) to short-circuit the
HTTP middleware in main.py: every endpoint except the allowlisted ones
returns 503 so concurrent writes can't race the operation.

`_scheduled_at` is a *future* timestamp the frontend's MaintenanceBanner
polls via GET /maintenance/status to render an "in N minutes" pre-warning.
The schedule-sweep cron endpoint (lands in 7b) sets this when it enqueues a
delayed sweep; the worker clears it the moment the job actually starts (the
banner is for warning the user before the window, not during).

Single-process assumption: both values are in-memory module globals. If the
backend ever runs multiple workers behind a load balancer, this becomes a
file sentinel or a DB row. Not in scope for v0.14.0.

Single-owner assumption: `_active` is a plain boolean, not a refcount. Today
only ONE code path drives a maintenance window at a time — either the worker
bracketing a sweep, or a synchronous restore (which executes on the request
thread while the worker is blocked by `is_maintenance_active()` in
`dispatch_one`). If a future change ever allows two owners to overlap (e.g.
an admin restore endpoint added to `_ALLOWED_PATHS` in
`core/maintenance_middleware.py`), the inner owner's finally will clear the
flag from under the outer owner. Either keep the single-owner invariant or
convert this to a refcount with explicit owners before allowlisting `/restore`
or any other destructive endpoint.

Flip logging: `set_maintenance` logs each actual flip at INFO with a
stack-tag so a stuck-flag report can be traced from logs alone.
"""

import logging
import traceback
from datetime import datetime

logger = logging.getLogger(__name__)

_active: bool = False
_scheduled_at: datetime | None = None


def is_maintenance_active() -> bool:
    return _active


def set_maintenance(active: bool) -> None:
    """Flip the maintenance gate. Real transitions log at INFO with a
    3-frame stack tag so a stuck-flag report can be traced from logs;
    no-op flips (steady-state test resets etc.) stay silent."""
    global _active
    if _active == active:
        return
    prior = _active
    _active = active
    # Caller frame + one above: enough to point at restore vs sweep
    # without serializing the whole stack into the log.
    stack_tag = " <- ".join(
        f"{frame.filename.rsplit('/', 1)[-1]}:{frame.lineno}"
        for frame in traceback.extract_stack(limit=4)[:-1]
    )
    logger.info(
        "Maintenance flag %s → %s (caller: %s)", prior, active, stack_tag,
    )


def get_scheduled_at() -> datetime | None:
    return _scheduled_at


def set_scheduled_at(when: datetime | None) -> None:
    global _scheduled_at
    _scheduled_at = when
