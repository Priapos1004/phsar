"""One-shot dev script: attribute pre-clustering seasonal-sweep children
to their parent sweep row.

Pre-this-commit, seasonal_sweep_dispatcher enqueued system user_scrape
children without setting `parent_job_id`. The schema FK landed alongside
the dispatcher change, so all new sweeps cluster correctly — but
historical rows remain unparented. This script attributes each
unparented `user_scrape` with `requested_by_user_id IS NULL` to the most
recent `seasonal_sweep` whose `created_at` precedes the child's.

Safe because the ONLY production source of `user_scrape` with
`requested_by_user_id IS NULL` is `seasonal_sweep_dispatcher` —
`enqueue_scrape` always stamps `current_user.id`. The time-based
heuristic can't misattribute a stray manual scrape because there
aren't any.

Idempotent: only updates rows where `parent_job_id IS NULL`. Re-runs
on already-backfilled DBs are no-ops.

Usage (read-only by default — pass `--apply` to mutate):
    python -m scripts.backfill_seasonal_sweep_parents
    python -m scripts.backfill_seasonal_sweep_parents --apply
"""

import argparse
import asyncio

from sqlalchemy import text

from app.core.db import async_session_maker

_PREVIEW_SQL = text(
    """
    SELECT
        (SELECT COUNT(*) FROM jobs WHERE kind = 'seasonal_sweep') AS sweeps,
        (
            SELECT COUNT(*) FROM jobs
            WHERE kind = 'user_scrape'
              AND requested_by_user_id IS NULL
              AND parent_job_id IS NULL
        ) AS unparented_children
    """,
)


_UPDATE_SQL = text(
    """
    UPDATE jobs c
    SET parent_job_id = parent.id
    FROM (
        SELECT s.id, s.created_at
        FROM jobs s
        WHERE s.kind = 'seasonal_sweep'
    ) parent
    WHERE c.kind = 'user_scrape'
      AND c.requested_by_user_id IS NULL
      AND c.parent_job_id IS NULL
      AND parent.created_at = (
          SELECT MAX(s2.created_at)
          FROM jobs s2
          WHERE s2.kind = 'seasonal_sweep'
            AND s2.created_at <= c.created_at
      )
    RETURNING c.id
    """,
)


async def main(apply: bool) -> None:
    async with async_session_maker() as session:
        row = (await session.execute(_PREVIEW_SQL)).one()
        print(f"seasonal_sweep rows: {row.sweeps}")
        print(f"unparented user_scrape rows with NULL user: {row.unparented_children}")
        if row.unparented_children == 0:
            print("Nothing to backfill.")
            return
        if not apply:
            print("Dry run — pass --apply to attribute these rows.")
            return
        updated = (await session.execute(_UPDATE_SQL)).rowcount
        await session.commit()
        print(f"Updated {updated} rows.")


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--apply", action="store_true", help="commit the update")
    args = parser.parse_args()
    asyncio.run(main(apply=args.apply))
