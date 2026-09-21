import enum
from datetime import date
from typing import TYPE_CHECKING

from sqlalchemy import (
    CheckConstraint,
    Date,
    Enum,
    Float,
    ForeignKey,
    Index,
    Integer,
    SQLColumnExpression,
    String,
    case,
    text,
)
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.ext.hybrid import hybrid_property
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.models.base import BaseModel

if TYPE_CHECKING:
    from app.models.anime import Anime
    from app.models.media_freshness import MediaFreshness
    from app.models.media_genre import MediaGenre
    from app.models.media_relation_edges import MediaRelationEdges
    from app.models.media_search import MediaSearch
    from app.models.media_studio import MediaStudio
    from app.models.ratings import Ratings
    from app.models.watchlist import Watchlist


class MediaType(str, enum.Enum):
    TV = "TV"
    TVSpecial = "TVSpecial"
    Movie = "Movie"
    OVA = "OVA"
    ONA = "ONA"
    Special = "Special"

class RelationType(str, enum.Enum):
    Main = "main"
    Summary = "summary"
    SideStory = "side_story"
    AlternativeVersion = "alternative_version"


# The story-advancing set. `main` is the canonical backbone; `alternative_version`
# covers retellings that extend or diverge from it (Evangelion Rebuild, Hokuto no Ken
# alts). Every question that turns on "does this advance the story" reads this set —
# what the spoiler frontier anchors on, what the MAL score averages over, which
# relations the watchlist's readiness filter treats as a season worth waiting for.
#
# A frozenset of enum MEMBERS, which `in` and `.in_()` both take — and because
# RelationType is a str-enum hashing by value, a plain `"main"` from a flat projection
# matches too, so no caller needs a `.value` conversion.
MAIN_STORY_RELATIONS = frozenset({RelationType.Main, RelationType.AlternativeVersion})

# Per-relation-type weights for the anime-level MAL "quality score" (the displayed
# avg score/votes AND the "Top N%" pill/search ranking, which share these inputs).
# An anime's score reflects its MAIN STORY (`MAIN_STORY_RELATIONS`); side stories and
# recaps are excluded (weight 0).
#
# Deliberately spelled out rather than derived from that set: this is the scoring dial
# alone, and a weight given to side stories here must not also change what
# `MAIN_STORY_RELATIONS` admits. Same answer today, different questions.
#
# This map is the SINGLE source of truth: the SQL twin (weighted_mean_*_expr in
# daos/search_filters.py) and the Python twin (anime_search_service
# ._compute_anime_aggregates) both read it, so changing a weight is the whole knob
# — giving side stories a small weight is a one-line edit.
#
# Why {1,1,0,0} deliberately (prod-data study + rejected alternatives): see
# compound-docs/2026-07-19-*.md.
RELATION_SCORE_WEIGHTS = {
    RelationType.Main: 1.0,
    RelationType.AlternativeVersion: 1.0,
    RelationType.SideStory: 0.0,
    RelationType.Summary: 0.0,
}

class SeasonType(str, enum.Enum):
    Winter = "Winter"
    Spring = "Spring"
    Summer = "Summer"
    Fall   = "Fall"


# Chronological rank of a season within its year. Lives beside the enum rather than in
# one of its consumers because both layers need it: services sort by it in Python, the
# watchlist DAO builds a SQL CASE from it. Keyed by members, but the str-enum hashes by
# value, so a caller holding a plain `"Fall"` looks up just as well.
#
# Distinct from `mal_scraper._SEASON_ORDER`, the lowercase MAL/URL vocabulary; this is
# the catalog's title-cased one.
SEASON_ORDER: dict[str, int] = {SeasonType.Winter: 1, SeasonType.Spring: 2, SeasonType.Summer: 3, SeasonType.Fall: 4}

# The sentinel `media.airing_status` values MAL returns. Here, beside the column
# that stores them, for the same reason as SEASON_ORDER above: both layers read
# them, and four DAOs filtering on `airing_status` should not have to import up
# into `services/` to name their own column's values. `relation_classifier` still
# owns what they *mean* — the substance gate reads them via _METADATA_PENDING_STATUSES.
AIRING_STATUS_CURRENTLY_AIRING = "Currently Airing"
AIRING_STATUS_FINISHED_AIRING = "Finished Airing"
AIRING_STATUS_NOT_YET_AIRED = "Not yet aired"

# Define ordered mapping to ensure correct prefix priority
AGE_RATING_MAP = [
    ("PG-13", 13),   # Must come before PG
    ("R+", 18),      # Must come before R
    ("R", 17),
    ("PG", 6),
    ("G", 0),
]

class Media(BaseModel):
    __tablename__ = "media"

    anime_id: Mapped[int] = mapped_column(Integer, ForeignKey("anime.id", ondelete="CASCADE"), nullable=False, index=True)
    mal_id: Mapped[int] = mapped_column(Integer, nullable=False, unique=True)
    mal_url: Mapped[str] = mapped_column(String, nullable=False)
    title: Mapped[str] = mapped_column(String, nullable=False)
    name_eng: Mapped[str | None] = mapped_column(String)
    name_jap: Mapped[str | None] = mapped_column(String)
    other_names: Mapped[list[str] | None] = mapped_column(JSONB, default=list)
    media_type: Mapped[MediaType] = mapped_column(Enum(MediaType), nullable=False)
    relation_type: Mapped[RelationType] = mapped_column(Enum(RelationType), nullable=False)
    age_rating: Mapped[str | None] = mapped_column(String)
    description: Mapped[str | None] = mapped_column(String)
    original_source: Mapped[str | None] = mapped_column(String)
    cover_image: Mapped[str | None] = mapped_column(String)
    score: Mapped[float | None] = mapped_column(Float, nullable=True)
    scored_by: Mapped[int] = mapped_column(Integer, nullable=False)
    episodes: Mapped[int | None] = mapped_column(Integer, nullable=True)
    anime_season_name: Mapped[SeasonType | None] = mapped_column(Enum(SeasonType), nullable=True)
    anime_season_year: Mapped[int | None] = mapped_column(Integer, nullable=True)
    airing_status: Mapped[str] = mapped_column(String, nullable=False)
    aired_from: Mapped[date | None] = mapped_column(Date, nullable=True)
    aired_to: Mapped[date | None] = mapped_column(Date, nullable=True)
    duration: Mapped[str | None] = mapped_column(String, nullable=True)
    duration_seconds: Mapped[int | None] = mapped_column(Integer, nullable=True)

    @hybrid_property
    def age_rating_numeric(self) -> int | None:
        """Returns numeric age rating based on MAL's age rating strings."""
        if not self.age_rating:
            return None

        normalized = self.age_rating.strip()
        for prefix, value in AGE_RATING_MAP:
            if normalized.startswith(prefix):
                return value
        return None

    # `inplace.expression` on a differently-named function, not a second
    # `def age_rating_numeric`: the two-same-names form reads as a redefinition to
    # every type checker. The hybrid still publishes under the property's name.
    @age_rating_numeric.inplace.expression
    @classmethod
    def _age_rating_numeric_expression(cls) -> SQLColumnExpression[int | None]:
        """SQL expression to compute numeric age rating using prefix matching."""
        return case(
            *[(cls.age_rating.startswith(prefix), value) for prefix, value in AGE_RATING_MAP],
            else_=None
        )

    @hybrid_property
    def total_watch_time(self) -> int | None:
        if self.episodes and self.duration_seconds:
            return self.episodes * self.duration_seconds
        return None

    @total_watch_time.inplace.expression
    @classmethod
    def _total_watch_time_expression(cls) -> SQLColumnExpression[int | None]:
        return case(
            (
                (cls.episodes.isnot(None) & cls.duration_seconds.isnot(None)),
                cls.episodes * cls.duration_seconds
            ),
            else_=None  # Changeable default value for total_watch_time = None
        )

    @hybrid_property
    def is_rateable(self) -> bool:
        """Whether this media can carry a rating at all — episode 1 has to have aired.

        One definition in both dialects, because it is needed in each:
        `rating_service._upsert_single_rating` refuses a *fresh* rating on anything
        else, and the rated-coverage counts in `RatingDAO.get_anime_coverage` scope
        their denominator to it. A tier must never be able to promise a state the
        rating endpoint would reject.

        Excluding the one refused status rather than listing the ones it accepts is
        deliberate: `mal_scraper` maps the statuses it knows and passes anything
        else through verbatim, so an unrecognised future value reads as rateable
        rather than silently becoming un-rateable everywhere at once.
        """
        return self.airing_status != AIRING_STATUS_NOT_YET_AIRED

    @is_rateable.inplace.expression
    @classmethod
    def _is_rateable_expression(cls) -> SQLColumnExpression[bool]:
        return cls.airing_status != AIRING_STATUS_NOT_YET_AIRED

    __table_args__ = (
        CheckConstraint(
            "anime_season_year >= 1900 AND anime_season_year <= 2200",
            name="check_season_year_4_digits"
        ),
        CheckConstraint(
            "(anime_season_name IS NULL AND anime_season_year IS NULL) "
            "OR (anime_season_name IS NOT NULL AND anime_season_year IS NOT NULL)",
            name="check_season_parts_both_or_none",
        ),
    )

    # Relationships
    anime: Mapped["Anime"] = relationship("Anime", back_populates="media", lazy="raise")
    ratings: Mapped[list["Ratings"]] = relationship("Ratings", back_populates="media", cascade="all, delete-orphan", lazy="raise")
    watchlist: Mapped[list["Watchlist"]] = relationship("Watchlist", back_populates="media", cascade="all, delete-orphan", lazy="raise")
    media_genre: Mapped[list["MediaGenre"]] = relationship("MediaGenre", back_populates="media", cascade="all, delete-orphan", lazy="raise")
    media_studio: Mapped[list["MediaStudio"]] = relationship("MediaStudio", back_populates="media", cascade="all, delete-orphan", lazy="raise")
    media_search: Mapped[list["MediaSearch"]] = relationship("MediaSearch", back_populates="media", cascade="all, delete-orphan", lazy="raise")
    # One-to-one freshness sidecar. See AnimeFreshness for rationale.
    freshness: Mapped["MediaFreshness | None"] = relationship(
        "MediaFreshness",
        back_populates="media",
        cascade="all, delete-orphan",
        uselist=False,
        lazy="raise",
    )
    # One-to-one MAL relation-edges sidecar. See MediaRelationEdges for rationale.
    relation_edges: Mapped["MediaRelationEdges | None"] = relationship(
        "MediaRelationEdges",
        back_populates="media",
        cascade="all, delete-orphan",
        uselist=False,
        lazy="raise",
    )

# Index to optimize queries filtering or ordering by season year and name
Index(
    "ix_media_year_season",
    Media.anime_season_year,
    Media.anime_season_name,
)

# The two indexes backing `AnimeDAO.select_due_media_for_sweep`'s tier atoms
# (`_media_sweep_atoms`). They must be declared HERE, not only in the migration
# that creates them: autogenerate proposes DROPping any index missing from the
# metadata, so a migration-only index is one unread diff away from taking the
# nightly sweep's access paths with it. `alembic check` in CI enforces this.
#
# Partial on the airing tier — "Currently Airing" is a small slice of the
# catalog, so the index stays a fraction of a full one on anime_id.
Index(
    "ix_media_airing_now",
    Media.anime_id,
    postgresql_where=text("airing_status = 'Currently Airing'"),
)
# Composite for the recent-main tier: anime_id groups, relation_type selects
# Main, aired_from is the range bound.
#
# Its first two columns also serve `watchlist_dao._franchise_signals`, which asks the
# same "this anime's main story" question without the date bound — so narrowing this
# index (making it partial on `relation_type = 'Main'`, say) would cost the watchlist
# page its access path too, not just the sweep's.
Index(
    "ix_media_main_aired_from",
    Media.anime_id,
    Media.relation_type,
    Media.aired_from,
)
