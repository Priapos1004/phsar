"""Inspect Anime rows + their media + raw relation edges (sidecars).

Usage (from `phsar/`):
    python -m scripts.inspect_anime_relations <substring>
"""

import argparse
import asyncio

from sqlalchemy import or_, select
from sqlalchemy.orm import selectinload

from app.core.db import async_session_maker
from app.models.anime import Anime
from app.models.media import Media


async def main(needle: str) -> None:
    pattern = f"%{needle}%"
    async with async_session_maker() as session:
        animes = (
            await session.execute(
                select(Anime)
                .where(
                    or_(
                        Anime.title.ilike(pattern),
                        Anime.name_eng.ilike(pattern),
                        Anime.name_jap.ilike(pattern),
                    )
                )
                .options(
                    selectinload(Anime.media)
                    .selectinload(Media.relation_edges)
                )
                .order_by(Anime.mal_id)
            )
        ).scalars().all()

        if not animes:
            print(f"No anime matched {needle!r}.")
            return

        for a in animes:
            print("=" * 80)
            print(f"Anime id={a.id} mal_id={a.mal_id} title={a.title!r}")
            print(f"  name_eng={a.name_eng!r} name_jap={a.name_jap!r}")
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
    parser = argparse.ArgumentParser()
    parser.add_argument("needle")
    args = parser.parse_args()
    asyncio.run(main(args.needle))
