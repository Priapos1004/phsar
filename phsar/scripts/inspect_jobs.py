"""Inspect recent jobs by payload substring.

Usage:
    python -m scripts.inspect_jobs overlord
"""

import argparse
import asyncio

from sqlalchemy import desc, select, text

from app.core.db import async_session_maker
from app.models.job import Job


async def main(needle: str) -> None:
    pattern = f"%{needle}%"
    async with async_session_maker() as session:
        stmt = (
            select(Job)
            .where(text("payload::text ILIKE :p"))
            .params(p=pattern)
            .order_by(desc(Job.created_at))
            .limit(15)
        )
        rows = (await session.execute(stmt)).scalars().all()

    if not rows:
        print(f"No jobs matched {needle!r}.")
        return

    for j in rows:
        print(
            f"uuid={str(j.uuid)[:8]} kind={j.kind.value:<14} "
            f"status={j.status.value:<10} "
            f"created={j.created_at.isoformat(timespec='seconds')} "
            f"payload={j.payload}"
        )
        if j.result_summary:
            print(f"  result: {j.result_summary}")


if __name__ == "__main__":
    p = argparse.ArgumentParser()
    p.add_argument("needle")
    args = p.parse_args()
    asyncio.run(main(args.needle))
