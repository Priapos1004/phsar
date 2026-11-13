"""Replay every user's natural history through the recommender and print the harness's report
(`recommender_eval.evaluate`) as JSON.

`--fit` refits too; its pooled weights are the values `WEIGHTS` takes after review.

`--dumps DIR` rebuilds each user's past watchlist from the backups in DIR by diffing them, read
straight out of the archives (`pg_restore --data-only --file=-`), never restored. Without it
there is no watchlist history (docs/features/recommender.md, "The ranking"). It reads the archives with whichever `pg_restore` is on PATH, so it must be PostgreSQL 17's
(scripts/CLAUDE.md says why).

Read-only. Usage (from `phsar/`):
    python -m scripts.backtest_recommender
    python -m scripts.backtest_recommender --fit --dumps ../backups_prod
"""

import argparse
import asyncio
import json
import math
import re
import subprocess
from collections import defaultdict
from datetime import UTC, datetime
from pathlib import Path

from app.core.db import async_session_maker
from app.services import recommender_compute as rc
from app.services import recommender_eval, recommender_service

_DUMP_TIME = re.compile(r"^phsar-(\d{8}-\d{6})")
# Where a rating explains an entry leaving the list: from the last backup holding it to this
# long after the first one without it.
_WATCHED_GRACE = 2 * rc.DAY


def _rows(dump: Path, table: str) -> list[dict[str, str | None]]:
    """A table's rows from a backup, by the COPY header's column names (older backups order
    and name columns differently); none when the backup predates the table."""
    text = subprocess.run(
        ["pg_restore", "--data-only", f"--table={table}", "--file=-", str(dump)],
        capture_output=True, text=True, check=True,
    ).stdout
    columns: list[str] | None = None
    rows = []
    for line in text.splitlines():
        if columns is None:
            if line.startswith(f"COPY public.{table} ("):
                columns = line[line.index("(") + 1 : line.index(")")].split(", ")
        elif line == "\\.":
            break
        else:
            rows.append({c: None if v == "\\N" else v for c, v in zip(columns, line.split("\t"), strict=True)})
    return rows


def _time(value: str) -> float:
    return datetime.fromisoformat(value).timestamp()


def _backups(directory: Path) -> list[tuple[float, Path]]:
    """The last backup of each UTC day, the larger file on a tie."""
    latest: dict[str, tuple[float, int, Path]] = {}
    for path in directory.glob("phsar-*.dump"):
        m = _DUMP_TIME.match(path.name)
        if m:
            t = datetime.strptime(m.group(1), "%Y%m%d-%H%M%S").replace(tzinfo=UTC).timestamp()
            latest[m.group(1)[:8]] = max(latest.get(m.group(1)[:8], (0.0, 0, path)), (t, path.stat().st_size, path))
    return sorted((t, path) for t, _, path in latest.values())


# A backup's watchlist: (user, media, listed at) → (priority, list name, last changed).
Snapshot = dict[tuple[int, int, float], tuple[int, str | None, float]]


def snapshots(directory: Path) -> list[tuple[float, Snapshot]]:
    """The watchlist in every backup that has one, oldest first."""
    out = []
    for t, path in _backups(directory):
        rows = _rows(path, "watchlist")
        if rows:
            tags = {r["id"]: r["name"] for r in _rows(path, "tag")}
            out.append((t, {
                (int(r["user_id"]), int(r["media_id"]), _time(r["created_at"])):
                    (int(r["priority"]), tags.get(r.get("tag_id")), _time(r["modified_at"]))
                for r in rows
            }))
    return out


def listings_from(snapshots: list[tuple[float, Snapshot]], rated_at: dict[tuple[int, int], float]) -> dict[int, list[rc.ListingRow]]:
    """Each user's watchlist stretches over the backups. An entry splits wherever a backup
    shows it changed, and leaves the list right after its media's rating when one falls
    between the last backup holding it and shortly after the first without it — so that pick
    sees it listed and the next one does not — else at that first backup. Entries listed and
    removed between two backups are not seen."""
    seen: dict[tuple[int, int, float], list[tuple[int, int, str | None, float]]] = defaultdict(list)
    for i, (_, entries) in enumerate(snapshots):
        for key, value in entries.items():
            seen[key].append((i, *value))
    out: dict[int, list[rc.ListingRow]] = defaultdict(list)
    for (user, media, created), versions in seen.items():
        last = versions[-1][0]
        until = None
        if last + 1 < len(snapshots):
            gone = snapshots[last + 1][0]
            rated = rated_at.get((user, media))
            watched = rated is not None and snapshots[last][0] <= rated <= gone + _WATCHED_GRACE
            until = rated + 1 if watched else gone
        stretches = [(created, versions[0][1], versions[0][2])]
        for _, priority, tag, modified in versions:
            if modified > stretches[-1][0]:
                stretches.append((modified, priority, tag))
        for (since, priority, tag), nxt in zip(stretches, [*stretches[1:], None], strict=True):
            out[user].append(rc.ListingRow(media, priority, since, nxt[0] if nxt else until, tag))
    return dict(out)


async def main(fit: bool, dumps: Path | None, lam: float) -> None:
    async with async_session_maker() as db:
        cat = await recommender_service.load_catalogue(db)
        histories = await recommender_service.load_histories(db)
    listings = {u: h.listings for u, h in histories.items()}
    listed_from = math.inf  # no watchlist history
    if dumps:
        rated_at = {(u, r.media_id): rc.event_time(r) for u, h in histories.items() for r in h.ratings}
        found = snapshots(dumps)
        rebuilt = listings_from(found, rated_at)
        # The history counts as whole from the first backup with a watchlist.
        listed_from = found[0][0]
        listings = {u: rebuilt.get(u, []) for u in histories}
    ledgers = {
        u: rc.ledger(cat, h.ratings, listings[u], franchise=h.franchise, listed_from=listed_from)
        for u, h in histories.items()
    }
    print(json.dumps(recommender_eval.evaluate(cat, ledgers, rc.WEIGHTS, refit=fit, lam=lam), indent=1))


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    parser.add_argument("--fit", action="store_true", help="refit the pooled weights and ablate each family")
    parser.add_argument("--dumps", type=Path, help="rebuild the past watchlists from the backups in this directory")
    parser.add_argument("--lam", type=float, default=recommender_eval.LAMBDA, help="the fit's L2 strength")
    args = parser.parse_args()
    asyncio.run(main(args.fit, args.dumps, args.lam))
