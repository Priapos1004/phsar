"""One-off: delete Anime rows whose title matches a substring.

FK cascades from anime.id clean up media, embeddings, freshness sidecars,
merge_candidates, ratings, user_visible_media, watchlists, etc.

Usage (from `phsar/`):
    python -m scripts.delete_anime_by_title overlord            # dry-run
    python -m scripts.delete_anime_by_title overlord --apply    # actually delete
"""

import argparse
import asyncio

from sqlalchemy import delete, func, or_, select

from app.core.db import async_session_maker
from app.models.anime import Anime
from app.models.media import Media


async def main(needle: str, apply: bool) -> None:
    pattern = f"%{needle}%"
    async with async_session_maker() as session:
        rows = (
            await session.execute(
                select(Anime).where(
                    or_(
                        Anime.title.ilike(pattern),
                        Anime.name_eng.ilike(pattern),
                        Anime.name_jap.ilike(pattern),
                    )
                ).order_by(Anime.mal_id)
            )
        ).scalars().all()

        if not rows:
            print(f"No anime matched {needle!r}.")
            return

        print(f"Matched {len(rows)} anime row(s):")
        for a in rows:
            media_count = (
                await session.execute(
                    select(func.count(Media.id)).where(Media.anime_id == a.id)
                )
            ).scalar_one()
            print(
                f"  id={a.id:>5} mal_id={a.mal_id:>6} "
                f"title={a.title!r} name_eng={a.name_eng!r} "
                f"({media_count} media)"
            )

        if not apply:
            print("\nDry-run — pass --apply to delete.")
            return

        ids = [a.id for a in rows]
        await session.execute(delete(Anime).where(Anime.id.in_(ids)))
        await session.commit()
        print(f"\nDeleted {len(ids)} anime row(s) (cascades applied).")


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("needle", help="Case-insensitive substring to match in title/name_eng/name_jap")
    parser.add_argument("--apply", action="store_true", help="Actually delete (default: dry-run)")
    args = parser.parse_args()
    asyncio.run(main(args.needle, args.apply))
