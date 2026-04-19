"""Process-wide maintenance flag.

Flipped on by the backup restore flow to short-circuit the HTTP middleware
in main.py: while a restore is running, every endpoint except the
allowlisted health + root routes returns 503 so concurrent writes can't
race against the pg_restore DROP+RESTORE cycle.

Single-process assumption: the flag is an in-memory module global. If the
backend ever runs multiple workers behind a load balancer, this becomes a
file sentinel or a DB row. Not in scope for v0.13.0.
"""

_active: bool = False


def is_maintenance_active() -> bool:
    return _active


def set_maintenance(active: bool) -> None:
    global _active
    _active = active
