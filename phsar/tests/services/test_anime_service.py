"""Tests for the season-suffix stripper and the
`create_anime_from_media` integration that applies it on new rows.
"""

import pytest
from sqlalchemy import select

from app.models.anime import Anime
from app.models.anime_search import AnimeSearch
from app.models.media import MediaType, RelationType
from app.schemas.media_schema import MediaUnconnected
from app.seeders.anime_title_backfiller import backfill_anime_title_suffixes
from app.services.anime_search_service import anime_title_texts
from app.services.anime_service import (
    create_anime_from_media,
    strip_season_suffix,
)
from app.services.vector_embedding_service import create_anime_embedding


def _media_in(mal_id: int, title: str, name_eng: str | None = None, name_jap: str | None = None) -> MediaUnconnected:
    return MediaUnconnected(
        mal_id=mal_id, mal_url=f"https://example/{mal_id}",
        title=title, name_eng=name_eng, name_jap=name_jap,
        media_type=MediaType.TV, relation_type=RelationType.Main,
        age_rating=None, description=None, original_source=None,
        cover_image=None, score=None, scored_by=0,
        episodes=None, anime_season_name=None, anime_season_year=None,
        airing_status="Finished Airing", aired_from=None, aired_to=None,
        duration=None, duration_seconds=None,
        genres=[], studio=[],
    )


# ---------------------------------------------------------------------------
# strip_season_suffix — English patterns
# ---------------------------------------------------------------------------

@pytest.mark.parametrize("before, after", [
    ("Shakugan no Shana: Season I", "Shakugan no Shana"),
    ("Shakugan no Shana: Season II", "Shakugan no Shana"),
    ("Vinland Saga Season 2", "Vinland Saga"),
    ("Vinland Saga Season 23", "Vinland Saga"),
    ("White Album 2nd Season", "White Album"),
    ("Tensei shitara Slime Datta Ken 3rd Season", "Tensei shitara Slime Datta Ken"),
    ("Boku no Hero Academia 7th Season", "Boku no Hero Academia"),
    ("Dr. Stone: Science Future Part 2", "Dr. Stone: Science Future"),
    ("Classroom of the Elite II", "Classroom of the Elite"),
    ("Classroom of the Elite III", "Classroom of the Elite"),
    # Iterative: stacked suffixes collapse
    ("Some Show Season 2 Part 2", "Some Show"),
])
def test_strip_season_suffix_english_strips(before, after):
    assert strip_season_suffix(before) == after


@pytest.mark.parametrize("text", [
    # Real subtitles after the suffix protect it
    "Tensei shitara Slime Datta Ken 3rd Season: Kanwa - Diablo Nikki",
    "Mushishi Zoku Shou: Suzu no Shizuku",
    # Roman numerals as part of canonical title (R2, X stay) — only the
    # explicit II..X list with leading whitespace strips.
    "Code Geass: Hangyaku no Lelouch R2",
    "Kimetsu no Yaiba: Yuukaku-hen",
    "Re:ZERO -Starting Life in Another World-",
    # Single-letter Roman that's actually a title token
    "X",
])
def test_strip_season_suffix_english_preserves(text):
    assert strip_season_suffix(text) == text


# ---------------------------------------------------------------------------
# strip_season_suffix — Japanese patterns
# ---------------------------------------------------------------------------

@pytest.mark.parametrize("before, after", [
    ("僕のヒーローアカデミア 第7期", "僕のヒーローアカデミア"),
    ("転生したらスライムだった件 第4期", "転生したらスライムだった件"),
    ("ぼっち・ざ・ろっく！ 2期", "ぼっち・ざ・ろっく！"),
    ("おでかけ子ザメ シーズン2", "おでかけ子ザメ"),
    ("Some Show セカンドシーズン", "Some Show"),
])
def test_strip_season_suffix_japanese_strips(before, after):
    assert strip_season_suffix(before, japanese=True) == after


@pytest.mark.parametrize("text", [
    # Dash-bracketed titles must not have trailing dashes stripped.
    "幻日のリムル -SUNSHINE in the SLIME-",
    "Darker than BLACK -黒の契約者-",
    "マッシュル-MASHLE-",
    "オーバーロード",
    "ナルト",
])
def test_strip_season_suffix_japanese_preserves(text):
    assert strip_season_suffix(text, japanese=True) == text


# ---------------------------------------------------------------------------
# Edge cases
# ---------------------------------------------------------------------------

def test_strip_season_suffix_none_passthrough():
    assert strip_season_suffix(None) is None
    assert strip_season_suffix(None, japanese=True) is None


def test_strip_season_suffix_empty_passthrough():
    assert strip_season_suffix("") == ""


def test_strip_season_suffix_only_suffix_falls_back():
    # If stripping would empty the string, return the original — never
    # destroy the value entirely.
    assert strip_season_suffix("Season 2") == "Season 2"


# ---------------------------------------------------------------------------
# create_anime_from_media integration: new rows get cleaned umbrella names
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_create_anime_strips_suffixes_on_save(db_session):
    media = _media_in(
        mal_id=88001,
        title="Vinland Saga Season 2",
        name_eng="Vinland Saga: Season II",
        name_jap="ヴィンランド・サガ 第2期",
    )
    anime = await create_anime_from_media(db_session, media)
    assert anime.title == "Vinland Saga"
    assert anime.name_eng == "Vinland Saga"
    assert anime.name_jap == "ヴィンランド・サガ"


@pytest.mark.asyncio
async def test_create_anime_leaves_clean_names_alone(db_session):
    media = _media_in(
        mal_id=88002,
        title="Naruto",
        name_eng="Naruto",
        name_jap="ナルト",
    )
    anime = await create_anime_from_media(db_session, media)
    assert anime.title == "Naruto"
    assert anime.name_eng == "Naruto"
    assert anime.name_jap == "ナルト"


# ---------------------------------------------------------------------------
# Backfiller seeder: existing dirty rows get cleaned + re-embedded
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_backfill_strips_existing_anime_and_regenerates_embedding(db_session):
    # Pre-strip-fix shaped row: title is clean, name_eng carries ": Season I"
    anime = Anime(
        mal_id=88003,
        title="Shakugan no Shana",
        name_eng="Shakugan no Shana: Season I",
        name_jap="灼眼のシャナ",
        description="A test anime",
    )
    db_session.add(anime)
    await db_session.flush()
    await create_anime_embedding(
        db_session, anime_id=anime.id,
        title_texts=anime_title_texts(anime),
        description_text=anime.description or "",
    )
    pre_embedding_id = (await db_session.execute(
        select(AnimeSearch.id).where(AnimeSearch.anime_id == anime.id)
    )).scalar_one()

    updated = await backfill_anime_title_suffixes(db_session)
    assert updated >= 1

    await db_session.refresh(anime)
    assert anime.name_eng == "Shakugan no Shana"
    assert anime.title == "Shakugan no Shana"
    assert anime.name_jap == "灼眼のシャナ"

    # Embedding was deleted + recreated → different row id
    new_embedding_id = (await db_session.execute(
        select(AnimeSearch.id).where(AnimeSearch.anime_id == anime.id)
    )).scalar_one()
    assert new_embedding_id != pre_embedding_id


@pytest.mark.asyncio
async def test_backfill_idempotent_on_clean_rows(db_session):
    """A second pass over already-clean rows must update zero rows."""
    anime = Anime(
        mal_id=88004,
        title="Already Clean Anime",
        name_eng="Already Clean Anime",
        name_jap=None,
        description="A test anime",
    )
    db_session.add(anime)
    await db_session.flush()
    await create_anime_embedding(
        db_session, anime_id=anime.id,
        title_texts=anime_title_texts(anime),
        description_text=anime.description or "",
    )

    # Backfiller commits internally; isolate this test's assertion to the
    # row we just added by counting the delta only.
    before_pass = await backfill_anime_title_suffixes(db_session)
    # If other rows in the catalog are dirty they may flip here — that's
    # the seeder doing its job. The relevant invariant is that a SECOND
    # pass over our specifically-clean row makes no further changes to it.
    await db_session.refresh(anime)
    assert anime.name_eng == "Already Clean Anime"

    # And the second pass touches zero rows globally.
    second_pass = await backfill_anime_title_suffixes(db_session)
    assert second_pass == 0
    _ = before_pass  # silence unused
