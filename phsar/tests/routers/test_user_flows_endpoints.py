"""Pin USER_FLOWS.md's endpoint table to the app's real route table.

Root CLAUDE.md sends readers to that table as the frontend's consumer view of the
API, and it is the part of that behavioural spec a machine can keep honest. So it
is checked rather than trusted.

The assertion lives in the backend suite because this is the only place with the
real route table: reconstructing it by parsing decorators means reimplementing
FastAPI's prefix nesting (`admin.py` mounts sub-routers, some declaring a prefix of
their own and some not), and a parser that gets that subtly wrong reports success
while checking nothing.

**One direction only.** Every row must name a route the app serves; the reverse is
not asserted, because "frontend-consumed" is not a property the route table carries.
`USER_FLOWS.md`'s own header says which direction is checked, and
`compound-docs/2026-08-12-frontend-docs-restructure.md` records why the completeness
half is left open.
"""

import re
from pathlib import Path

from app.main import create_app

USER_FLOWS = Path(__file__).resolve().parents[2] / "frontend" / "USER_FLOWS.md"

# A row reads: | `/ratings/media/{uuid}` | PUT | Create or update a rating |
_ROW = re.compile(r"\|\s*`([^`]+)`\s*\|\s*(GET|POST|PUT|PATCH|DELETE)\s*\|")


def _normalise(path: str) -> str:
    """Drop any query string and blank out path-param names.

    The doc names params for the reader (`{uuid}`) where the route may call them
    something else (`{anime_uuid}`); only the shape is being compared.
    """
    return re.sub(r"\{[^}]*\}", "{}", path.split("?")[0])


def _table_rows() -> list[str]:
    """Every data row of section 13's table.

    The first two `|` lines are the column header and its `|---|` rule; anything
    after them is data, including a row that no longer parses.
    """
    lines = USER_FLOWS.read_text(encoding="utf-8").splitlines()
    start = next(i for i, line in enumerate(lines) if line.startswith("## 13."))
    end = next(
        (i for i in range(start + 1, len(lines)) if lines[i].startswith("## ")),
        len(lines),
    )
    table = [line for line in lines[start:end] if line.lstrip().startswith("|")]
    return table[2:]


def _actual_endpoints() -> set[tuple[str, str]]:
    return {
        (_normalise(route.path), method)
        for route in create_app().routes
        if getattr(route, "methods", None)
        for method in route.methods
    }


def test_documented_endpoints_all_exist():
    rows = _table_rows()
    matches = [(line, _ROW.search(line)) for line in rows]

    # Every data row must parse. A row-count floor would let a reformat take most
    # of the table out of the check while still passing — a guard against silent
    # blindness that is itself silently partial.
    unparsed = [line for line, m in matches if m is None]
    assert not unparsed, (
        f"{len(unparsed)} of {len(rows)} rows in USER_FLOWS.md section 13 no longer "
        "parse, so they are not being checked:\n" + "\n".join(f"  {r}" for r in unparsed)
    )

    documented = {(_normalise(m.group(1)), m.group(2)) for _, m in matches if m}
    missing = sorted(documented - _actual_endpoints())
    assert not missing, "USER_FLOWS.md section 13 documents endpoints the app does not serve:\n" + "\n".join(
        f"  {method:6} {path}" for path, method in missing
    )
