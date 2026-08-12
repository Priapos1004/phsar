"""Pin USER_FLOWS.md's endpoint table to the app's real route table.

Root CLAUDE.md sends readers to that table as the frontend's consumer view of the
API, and it is the one part of a 96 KB behavioural spec a machine can keep honest.
So it is checked rather than trusted.

The assertion lives in the backend suite because this is the only place with the
real route table: reconstructing it by parsing decorators means reimplementing
FastAPI's prefix nesting (`admin.py` mounts four sub-routers that declare no prefix
of their own, plus a `/backups` one that does), and a parser that gets that subtly
wrong reports success while checking nothing.

One direction only. Plenty of routes are not frontend-consumed — `/save`, `/seed`,
the cron-authed schedulers — and the table does not claim to list them.
"""

import re
from pathlib import Path

from app.main import create_app

USER_FLOWS = (
    Path(__file__).resolve().parents[3] / "phsar" / "frontend" / "USER_FLOWS.md"
)

# A row reads: | `/ratings/media/{uuid}` | PUT | Create or update a rating |
_ROW = re.compile(r"\|\s*`([^`]+)`\s*\|\s*(GET|POST|PUT|PATCH|DELETE)\s*\|")

# Below this, assume the parser broke rather than that the table shrank — a
# zero-row pass is the one way this check could silently stop checking anything.
MIN_ROWS = 40


def _normalise(path: str) -> str:
    """Drop any query string and blank out path-param names.

    The doc names params for the reader (`{uuid}`) where the route may call them
    something else (`{anime_uuid}`); only the shape is being compared.
    """
    return re.sub(r"\{[^}]*\}", "{}", path.split("?")[0])


def _documented_endpoints() -> set[tuple[str, str]]:
    lines = USER_FLOWS.read_text().splitlines()
    start = next(i for i, line in enumerate(lines) if line.startswith("## 13."))
    end = next(
        (i for i in range(start + 1, len(lines)) if lines[i].startswith("## ")),
        len(lines),
    )
    return {
        (_normalise(m.group(1)), m.group(2))
        for line in lines[start:end]
        if (m := _ROW.search(line))
    }


def _actual_endpoints() -> set[tuple[str, str]]:
    return {
        (_normalise(route.path), method)
        for route in create_app().routes
        if getattr(route, "methods", None)
        for method in route.methods
    }


def test_documented_endpoints_all_exist():
    documented = _documented_endpoints()
    assert len(documented) >= MIN_ROWS, (
        f"parsed only {len(documented)} rows from USER_FLOWS.md section 13 — "
        "the table's format probably changed and this check is no longer reading it"
    )

    missing = sorted(documented - _actual_endpoints())
    assert not missing, "USER_FLOWS.md section 13 documents endpoints the app does not serve:\n" + "\n".join(
        f"  {method:6} {path}" for path, method in missing
    )
