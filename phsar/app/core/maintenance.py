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
"""

from datetime import datetime

_active: bool = False
_scheduled_at: datetime | None = None


def is_maintenance_active() -> bool:
    return _active


def set_maintenance(active: bool) -> None:
    global _active
    _active = active


def get_scheduled_at() -> datetime | None:
    return _scheduled_at


def set_scheduled_at(when: datetime | None) -> None:
    global _scheduled_at
    _scheduled_at = when
