"""Discover's description rows on the current model, through the running backend.

Run from `phsar/` with the backend up (it logs in as the admin from `.env`):
    PYTHONPATH=. ../.venv/bin/python ../.claude/skills/remeasure-embeddings/discover_rows.py

Prints, per description row, its pool and its semantic-only hits (the anime no literal
match brought in), and every pair of a mood's rows over the overlap bar in
docs/features/browse.md, counted as it counts it, with how many of the shared anime are
semantic hits. How to read them is in SKILL.md beside this file. Rows are measured as a new
viewer opens them: the per-viewer "not watched" toggle is left out.
"""
import asyncio
import itertools
import json

import httpx
from dotenv import dotenv_values
from sqlalchemy import Text, cast, distinct, select

from app.core.db import async_session_maker
from app.daos.search_filters import description_text, literal_matches
from app.models.anime import Anime
from app.models.media import Media

ROW_SIZE = 25  # the frontend's `ROW_SIZE`
BAR = 5


def login() -> httpx.Client:
    env = dotenv_values(".env")
    c = httpx.Client(base_url="http://localhost:8000", timeout=120)
    r = c.post("/auth/login", data={"username": env["ADMIN_USERNAME"], "password": env["ADMIN_PASSWORD"]})
    r.raise_for_status()
    c.headers["Authorization"] = f"Bearer {r.json()['access_token']}"
    return c


def search(c: httpx.Client, row: dict, limit: int) -> list[dict]:
    params = {k: (json.dumps(v) if isinstance(v, dict) else v) for k, v in row["params"].items() if k != "rated"}
    r = c.get("/search/anime", params={**params, "limit": limit})
    r.raise_for_status()
    return r.json()


async def literal_hits(queries: list[str]) -> dict[str, set[str]]:
    """Per query, the anime with a media its literal tier's strict test matches — the
    search's own test over the search's own text, so the semantic-only part below is
    what the model added."""
    out = {}
    async with async_session_maker() as s:
        for query in queries:
            out[query] = set((await s.execute(
                select(distinct(cast(Anime.uuid, Text))).join(Media, Media.anime_id == Anime.id)
                .where(literal_matches(query, description_text())[0])
            )).scalars())
    return out


def main() -> None:
    c = login()
    moods = {m["key"]: c.get(f"/browse/moods/{m['key']}").json()["carousels"] for m in c.get("/browse/moods").json()["moods"]}
    rows = {r["key"]: r for carousels in moods.values() for r in carousels}
    described = {k: r for k, r in rows.items() if r["params"].get("search_type") == "description"}
    literal = asyncio.run(literal_hits(sorted({r["params"]["query"] for r in described.values()})))

    print("DESCRIPTION ROWS — pool, semantic-only hits (should read on topic)")
    semantic: dict[str, set[str]] = {}
    for key, row in described.items():
        pool = search(c, row, 1000)
        tail = [a for a in pool if a["uuid"] not in literal[row["params"]["query"]]]
        semantic[key] = {a["uuid"] for a in tail}
        print(f"  {key:16} {row['params']['query']!r:16} pool {len(pool):4}  semantic {len(tail):3}  {[a['title'][:30] for a in tail[:6]]}")

    print(f"\nOVERLAP — pairs sharing more than {BAR}: the pools when either row draws at random, else the first {ROW_SIZE} tiles")
    pools = {k: {a["uuid"] for a in search(c, r, 1000)} for k, r in rows.items()}
    tiles = {k: {a["uuid"] for a in search(c, r, ROW_SIZE)} for k, r in rows.items()}
    for mood, carousels in moods.items():
        for a, b in itertools.combinations(carousels, 2):
            random = "random" in (a["params"].get("sort"), b["params"].get("sort"))
            counted = pools if random else tiles
            shared = counted[a["key"]] & counted[b["key"]]
            if len(shared) > BAR:
                by_model = shared & (semantic.get(a["key"], set()) | semantic.get(b["key"], set()))
                print(f"  {mood:14} {a['key']:16} {b['key']:16} {len(shared)}  semantic hits among them: {len(by_model)}")


if __name__ == "__main__":
    main()
