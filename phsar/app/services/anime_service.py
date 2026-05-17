import logging
import re

from sqlalchemy.ext.asyncio import AsyncSession

from app.daos.anime_dao import AnimeDAO
from app.exceptions import MalIdAlreadyExistsError
from app.models.anime import Anime
from app.schemas.media_schema import MediaUnconnected

logger = logging.getLogger(__name__)

anime_dao = AnimeDAO()


# Season-suffix patterns stripped from the Anime UMBRELLA title fields when
# a new row is created. Media rows keep their full per-season titles —
# media is the per-season identity. The umbrella should read like the
# franchise name without the season tag.
#
# Patterns are end-anchored and applied iteratively until idempotent so
# stacked suffixes ("S2 Part 2") collapse cleanly. Roman numerals use an
# explicit list (II..X) instead of a generic [IVX]+ to avoid eating
# legitimate one-letter title tokens like "X" or fragments of words.
#
# Iteration bound is a safety net: each pass strips at most one suffix
# layer, and 5 covers any sane stacking depth ("Final Season Part II"
# style is already two layers). Higher would be hiding a regex bug.
_STRIP_MAX_ITERATIONS = 5
_EN_SUFFIX_PATTERNS = [
    re.compile(r":\s+Season\s+[IVX]+$", re.IGNORECASE),       # ": Season I"
    re.compile(r"\s+Season\s+\d+$", re.IGNORECASE),            # " Season 2"
    re.compile(r"\s+Season\s+[IVX]+$", re.IGNORECASE),         # " Season II"
    re.compile(r"\s+\d+(?:st|nd|rd|th)\s+Season$", re.IGNORECASE),  # " 2nd Season"
    re.compile(r"\s+Part\s+\d+$", re.IGNORECASE),              # " Part 2"
    re.compile(r"\s+Part\s+[IVX]+$", re.IGNORECASE),           # " Part II"
    re.compile(r"\s+(?:II|III|IV|V|VI|VII|VIII|IX|X)$"),       # " II"
]

# Japanese season markers in title_japanese. 第N期 is the canonical form
# (期 = "period/term"); シーズンN is the katakana loanword; bare N期 also
# occurs. False-positive risk is low because these glyphs only carry the
# "season" meaning in this final position.
_JP_SUFFIX_PATTERNS = [
    re.compile(r"\s*第[0-9一二三四五六七八九十]+期$"),
    re.compile(r"\s*[0-9]+期$"),
    re.compile(r"\s*シーズン[0-9]+$"),
    re.compile(r"\s*セカンドシーズン$"),
    re.compile(r"\s*サードシーズン$"),
]


def strip_season_suffix(value: str | None, *, japanese: bool = False) -> str | None:
    """Strip recognised season-suffix patterns from an anime umbrella name.
    Iterates until idempotent so stacked markers collapse. Returns the
    input unchanged when nothing matches; preserves None passthrough so
    callers can pipe nullable fields straight through."""
    if not value:
        return value
    patterns = _JP_SUFFIX_PATTERNS if japanese else _EN_SUFFIX_PATTERNS
    out = value
    for _ in range(_STRIP_MAX_ITERATIONS):
        prev = out
        for pat in patterns:
            out = pat.sub("", out)
        out = out.strip()  # whitespace only — never strip punctuation, it's often canonical (e.g. trailing dashes in "Re:ZERO -...-")
        if out == prev:
            break
    return out or value  # fall back to original if stripping emptied the string


async def create_anime_from_media(db: AsyncSession, anime_as_media_in: MediaUnconnected) -> Anime:
    logger.debug(f"DB session: {id(db)}")
    # Check if anime already exists in the database
    existing = await anime_dao.get_by_mal_id(db, anime_as_media_in.mal_id)
    if existing:
        raise MalIdAlreadyExistsError(anime_as_media_in.mal_id, anime_as_media_in.title)

    # Strip season suffixes from the umbrella name fields. The first media
    # in the BFS graph is often a Season N entry, so its title can carry
    # "Season 2" / "第2期" / etc. that don't belong on the franchise row.
    data = anime_as_media_in.model_dump(
        include={
            "mal_id",
            "title",
            "name_eng",
            "name_jap",
            "other_names",
            "description",
            "cover_image",
        }
    )
    data["title"] = strip_season_suffix(data["title"]) or data["title"]
    data["name_eng"] = strip_season_suffix(data["name_eng"])
    data["name_jap"] = strip_season_suffix(data["name_jap"], japanese=True)

    anime_obj = Anime(**data)
    await anime_dao.create(db, anime_obj)
    return anime_obj
