"""Read-only audit for cross-franchise contamination in the catalog.

Wraps `find_disjoint_franchises` (the production detection function) for
console + JSON output. The function itself lives in
`app.services.relation_classifier` so the same logic runs at scrape,
backfill, merge-survivor sites and here — keeping the audit-as-spec
contract.

Usage (from `phsar/`):
    python -m scripts.audit_cross_franchise

Read-only: no commits, no MAL calls. Safe to run repeatedly.
"""

import asyncio
import json
import logging
from pathlib import Path

from sqlalchemy import select
from sqlalchemy.orm import selectinload

from app.core.db import async_session_maker
from app.models.anime import Anime
from app.models.media import Media
from app.services.anime_relation_service import build_classifier_graph
from app.services.relation_classifier import (
    classify_anime_relations,
    find_disjoint_franchises,
)

logging.basicConfig(level=logging.WARNING, format="%(message)s")

OUTPUT_PATH = Path(__file__).resolve().parent / "audit_cross_franchise.json"


async def audit():
    suspects = []
    async with async_session_maker() as session:
        all_anime = (
            await session.execute(
                select(Anime).options(
                    selectinload(Anime.media).selectinload(Media.relation_edges)
                )
            )
        ).scalars().all()

        for anime in all_anime:
            if not anime.media:
                continue

            graph, edges = build_classifier_graph(anime.media)
            classifications, anchor = classify_anime_relations(graph, edges)
            if anchor is None:
                continue

            franchises = find_disjoint_franchises(graph, edges, anchor)
            if not franchises:
                continue

            media_by_mal = {m.mal_id: m for m in anime.media}

            def _label(mal_id: int) -> str:
                m = media_by_mal.get(mal_id)
                if m is None:
                    return f"<external mal_id={mal_id}>"
                rt = classifications.get(mal_id, "?")
                return (
                    f"mal_id={mal_id} type={m.media_type.value} rel={rt} "
                    f"title={m.title!r}"
                )

            suspects.append({
                "anime_id": anime.id,
                "anime_mal_id": anime.mal_id,
                "anime_title": anime.title,
                "media_count": len(anime.media),
                "anchor": _label(anchor),
                "disjoint_franchises": [
                    {
                        "members": [_label(mid) for mid in f["member_mal_ids"]],
                        "substance_members": [
                            _label(mid) for mid in f["substance_member_mal_ids"]
                        ],
                        "suggested_anchor": _label(f["suggested_anchor_mal_id"]),
                        "bridge_edges": [
                            {"from": _label(a), "to": _label(b), "rel": rel}
                            for a, b, rel in f["bridge_edges"]
                        ],
                    }
                    for f in franchises
                ],
            })

    return suspects


def _summarize(suspects: list[dict]) -> None:
    print()
    print("=" * 80)
    print(f"Suspect rows flagged: {len(suspects)}")
    print("=" * 80)

    if not suspects:
        print("No cross-franchise contamination detected.")
        return

    # Worst rows first: by # of disjoint clusters desc, then total
    # cluster members desc. A row with 2 clusters of 3 sorts before
    # 1 cluster of 5.
    suspects.sort(
        key=lambda s: (
            -len(s["disjoint_franchises"]),
            -sum(len(c["members"]) for c in s["disjoint_franchises"]),
        ),
    )

    for suspect in suspects:
        print()
        print(
            f"[anime_id={suspect['anime_id']} mal_id={suspect['anime_mal_id']}] "
            f"{suspect['anime_title']!r}"
        )
        print(f"  total media: {suspect['media_count']}")
        print(f"  anchor: {suspect['anchor']}")
        for i, cluster in enumerate(suspect["disjoint_franchises"], 1):
            print(
                f"  disjoint franchise #{i} "
                f"({len(cluster['members'])} media, "
                f"{len(cluster['substance_members'])} substance-passing):"
            )
            print(f"    suggested anchor: {cluster['suggested_anchor']}")
            for label in cluster["members"]:
                print(f"    - {label}")
            if cluster["bridge_edges"]:
                print("    bridge edges to anchored set:")
                for be in cluster["bridge_edges"]:
                    print(f"      {be['from']} -[{be['rel']}]-> {be['to']}")
            else:
                print("    no bridge edges (orphan reachable only via dropped/dangling edges)")


async def main() -> None:
    suspects = await audit()
    _summarize(suspects)
    OUTPUT_PATH.write_text(json.dumps(suspects, indent=2, default=str))
    print()
    print(f"Wrote JSON dump to {OUTPUT_PATH}")


if __name__ == "__main__":
    asyncio.run(main())
