"""One-off dry-run audit for the relation backfiller.

Usage (from `phsar/`):
    python -m scripts.audit_relation_backfill

Connects to the live dev DB, runs `backfill_relations(dry_run=True)`,
and prints a per-anime digest. No writes; safe to run repeatedly.
"""

import asyncio
import logging

from app.core.db import async_session_maker
from app.seeders.relation_backfiller import backfill_relations

logging.basicConfig(level=logging.WARNING, format="%(message)s")


async def main() -> None:
    async with async_session_maker() as session:
        summary = await backfill_relations(session, dry_run=True)

    print()
    print("=" * 80)
    print(f"Scanned:           {summary['anime_scanned']:>4} anime")
    print(f"Would change:      {summary['anime_changed']:>4} anime")
    print(f"Media reclassified:{summary['media_reclassified']:>4}")
    print(f"Anchor changes:    {summary['anchor_changes']:>4}")
    print("=" * 80)

    if not summary["diffs"]:
        print("No changes — catalog already matches the new classifier.")
        return

    for diff in summary["diffs"]:
        print()
        print(f"[anime_id={diff['anime_id']}] {diff['anime_title']!r}")
        if diff["anchor_changed"]:
            print(
                f"  ANCHOR: mal_id {diff['old_anchor_mal_id']} → {diff['new_anchor_mal_id']}"
            )
        for mal_id, old_rt, new_rt in diff["reclassified"]:
            print(f"  media mal_id={mal_id}: {old_rt} → {new_rt}")


if __name__ == "__main__":
    asyncio.run(main())
