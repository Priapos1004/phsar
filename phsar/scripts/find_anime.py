"""Find anime by mal_id OR by substring across title / name_eng / name_jap /
other_names (JSONB) — last one is what `inspect_anime_relations` missed.

Usage (from `phsar/`):
    python -m scripts.find_anime kage
    python -m scripts.find_anime --mal 49470
"""

import argparse
import asyncio

from sqlalchemy import Text, cast, or_, select
from sqlalchemy.orm import selectinload

from app.core.db import async_session_maker
from app.models.anime import Anime
from app.models.media import Media


async def main(needle: str | None, mal_id: int | None) -> None:
    async with async_session_maker() as session:
        if mal_id is not None:
            stmt = (
                select(Anime).where(Anime.mal_id == mal_id)
                .options(
                    selectinload(Anime.media).selectinload(Media.relation_edges)
                )
            )
        else:
            pattern = f"%{needle}%"
            stmt = (
                select(Anime).where(
                    or_(
                        Anime.title.ilike(pattern),
                        Anime.name_eng.ilike(pattern),
                        Anime.name_jap.ilike(pattern),
                        cast(Anime.other_names, Text).ilike(pattern),
                    )
                )
                .options(
                    selectinload(Anime.media).selectinload(Media.relation_edges)
                )
                .order_by(Anime.mal_id)
            )

        animes = (await session.execute(stmt)).scalars().unique().all()

        if not animes:
            print("No anime matched.")
            return

        for a in animes:
            print("=" * 80)
            print(f"Anime id={a.id} mal_id={a.mal_id} title={a.title!r}")
            print(f"  name_eng={a.name_eng!r} name_jap={a.name_jap!r}")
            print(f"  other_names={a.other_names}")
            print(f"  media count: {len(a.media)}")
            for m in sorted(a.media, key=lambda x: (x.aired_from is None, x.aired_from, x.mal_id)):
                edges = m.relation_edges
                edge_repr = "<none>" if edges is None else edges.edges
                print(
                    f"    media id={m.id} mal_id={m.mal_id:>6} "
                    f"type={m.media_type.value:<8} rel={m.relation_type.value:<20} "
                    f"title={m.title!r}"
                )
                print(f"        edges: {edge_repr}")


if __name__ == "__main__":
    p = argparse.ArgumentParser()
    p.add_argument("needle", nargs="?", default=None)
    p.add_argument("--mal", type=int, default=None, dest="mal_id")
    args = p.parse_args()
    if args.needle is None and args.mal_id is None:
        p.error("provide a substring or --mal <id>")
    asyncio.run(main(args.needle, args.mal_id))
