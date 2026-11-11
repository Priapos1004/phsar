"""The two margin studies behind `SEMANTIC_MARGIN`, on the current model.

Run from `phsar/` against a prod restore that the app has already re-embedded:
    PYTHONPATH=. ../.venv/bin/python ../.claude/skills/remeasure-embeddings/margins.py

Prints, per margin, how many SEMANTIC-ONLY hits (literal hits excluded) each query admits:
media for descriptions (the whole catalogue), the admin's notes for notes. The rules are in
SKILL.md beside this file; it reads the app's own cutoff pieces, so it measures what search
does.
"""
import asyncio

from sqlalchemy import not_, select

from app.core.config import settings
from app.core.db import async_session_maker
from app.daos.rating_dao import _note_distance, note_cutoff
from app.daos.search_filters import (
    SEMANTIC_MARGIN,
    _description_distance,
    description_cutoff,
    description_text,
    literal_matches,
)
from app.models.media import Media
from app.models.media_search import MediaSearch
from app.models.rating_search import RatingSearch
from app.models.ratings import Ratings
from app.models.users import Users
from app.services.vector_embedding_service import generate_query_embedding

MARGINS = [0.02, 0.03, 0.04, 0.05, 0.06, 0.07, 0.08, 0.10, 0.15, 0.20, 0.25, 0.30]

NAMES = ["shinji", "izumi", "rintaro", "okabe"]
NONSENSE = ["xyzzy", "spreadsheet", "tax audit", "asdf qwer"]
RELEVANT = [
    "giant robots", "a boy who can see ghosts", "detective solves murders",
    "friends start a band in high school", "a girl who travels back in time",
    "vampire", "吸血鬼", "タイムトラベル", "Zeitreise", "isekai reincarnation",
]
NOTES_OWN = ["ecchi", "wholesome", "leveling", "murder mystery", "cliffhanger", "world building",
             "plot twist", "music", "boring", "female MC"]
NOTES_PARAPHRASE = ["heartwarming", "detective story", "unresolved ending", "calm and cozy", "songs",
                    "dull and tedious", "hilarious", "the hero gets stronger", "unexpected turn",
                    "artificial intelligence", "sad and touching", "lewd scenes", "food"]
NOTES_NOISE = ["xyzzy", "spreadsheet", "tax audit", "submarine", "pizza recipe", "good", "nice"]


def admitted(mean: float, rows) -> list[int]:
    return [sum(1 for _, d in rows if d <= mean - m) for m in MARGINS]


async def description(session, query: str):
    embedding = await generate_query_embedding(query)
    distance = _description_distance(embedding)
    mean = (await session.execute(select(description_cutoff(embedding)))).scalar_one() + SEMANTIC_MARGIN
    rows = (await session.execute(
        select(Media.title, distance).join(MediaSearch, MediaSearch.media_id == Media.id)
        .where(Media.description != "", not_(literal_matches(query, description_text())[0]))
        .order_by(distance).limit(80)
    )).all()
    return mean, rows


async def notes(session, query: str, user_id: int):
    embedding = await generate_query_embedding(query)
    distance = _note_distance(embedding)
    mean = (await session.execute(select(note_cutoff(embedding, user_id)))).scalar_one() + SEMANTIC_MARGIN
    rows = (await session.execute(
        select(Ratings.note, distance).join(RatingSearch, RatingSearch.rating_id == Ratings.id)
        .where(Ratings.user_id == user_id, not_(literal_matches(query, Ratings.note)[0]))
        .order_by(distance).limit(80)
    )).all()
    return mean, rows


async def main():
    async with async_session_maker() as session:
        print("margins:", MARGINS)
        print("\nDESCRIPTIONS — names and nonsense (rule: every one admits <= 2)")
        worst = [0] * len(MARGINS)
        for query in NAMES + NONSENSE:
            mean, rows = await description(session, query)
            counts = admitted(mean, rows)
            worst = [max(a, b) for a, b in zip(worst, counts, strict=True)]
            print(f"  {query:<14} {counts}")
        print(f"  {'WORST':<14} {worst}")
        print("\nDESCRIPTIONS — relevant queries (read the survivors at the chosen margin)")
        for query in RELEVANT:
            mean, rows = await description(session, query)
            print(f"  {query:<38} {admitted(mean, rows)}")
            print("      " + "; ".join(f"{t[:26]} {d:.3f}" for t, d in rows[:8]))

        user_id = (await session.execute(
            select(Users.id).where(Users.username == settings.ADMIN_USERNAME))).scalar_one()
        print("\nNOTES (the admin's) — rule: noise admits 0; paraphrases should find their notes")
        for group, queries in (("own", NOTES_OWN), ("para", NOTES_PARAPHRASE), ("noise", NOTES_NOISE)):
            for query in queries:
                mean, rows = await notes(session, query, user_id)
                nearest = "; ".join(f"{(t or '')[:30]!r} {d:.3f}" for t, d in rows[:3])
                print(f"  {group:<5} {query:<24} {admitted(mean, rows)}  {nearest}")


asyncio.run(main())
