import logging

from pgvector.sqlalchemy import Vector
from sqlalchemy import Numeric, Text, and_, case, cast, distinct, func, select, tuple_
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.anime import Anime
from app.models.genre import Genre
from app.models.media import (
    AGE_RATING_TIERS,
    AIRING_STATUS_CURRENTLY_AIRING,
    AIRING_STATUS_FINISHED_AIRING,
    AIRING_STATUS_NOT_YET_AIRED,
    RELATION_SCORE_WEIGHTS,
    Media,
    SeasonType,
)
from app.models.media_genre import MediaGenre
from app.models.media_search import MediaSearch
from app.models.media_studio import MediaStudio
from app.models.studio import Studio
from app.schemas.media_filter_schema import MediaSearchFilters, SearchType

logger = logging.getLogger(__name__)

# Base mapping from search type to the embedding column used for cosine distance ordering
_VECTOR_COLUMNS = {
    SearchType.DESCRIPTION: MediaSearch.description_embedding,
}


def weighted_score_expr(score, scored_by):
    """Confidence-weighted MAL score `score * log10(scored_by + 1)` — log10 (not
    ln) dampens the vote-count weight so a very popular but mediocre title can't
    outrank a higher-scored niche one. Single source of truth for the SQL form,
    shared by media + anime search ranking and the `score_top_percent` percentile
    DAOs (the Python twin is `scrape_dispatcher._weighted_score`). `score` /
    `scored_by` may be plain columns (per-media, media DAOs) or the per-anime
    weighted means (`weighted_mean_score_expr` / `weighted_mean_votes_expr`).

    The base is passed explicitly (`log(10, x)`) rather than relying on
    Postgres's single-arg `log()` defaulting to base 10, so the SQL stays
    numerically locked to the Python twin's `math.log10` even if the dialect
    changes — `test_weighted_score_matches_python_twin` guards the equivalence."""
    return score * func.log(10, scored_by + 1)


def _score_weight_case():
    """CASE mapping `Media.relation_type` → its `RELATION_SCORE_WEIGHTS` weight
    (unknown/unmapped → 0). SQL twin of the Python weight lookup in
    `anime_search_service._compute_anime_aggregates`."""
    whens = [
        (Media.relation_type == rt, float(w))
        for rt, w in RELATION_SCORE_WEIGHTS.items()
    ]
    return case(*whens, else_=0.0)


def _relation_weighted_mean(value_col):
    """`Σ(w·value) / Σ(w)` over an anime's media that have a non-null score,
    weighted by relation type (`RELATION_SCORE_WEIGHTS`). Aggregate expression —
    use under a per-anime GROUP BY. NULL when the anime has no scored,
    positively-weighted media (only side stories/recaps scored → the anime reads
    as unscored, matching the display twin)."""
    w = _score_weight_case()
    scored = Media.score.is_not(None)
    num = func.sum(w * value_col).filter(scored)
    den = func.sum(w).filter(scored)
    # Cast to Numeric: weighted_score_expr's two-arg log(10, x) requires
    # numeric, but this division yields double precision.
    return cast(num / func.nullif(den, 0.0), Numeric)


def weighted_mean_score_expr():
    """Per-anime relation-weighted mean MAL score (`S_w`) — the displayed
    `avg_score` and the score half of the ranking/pill metric."""
    return _relation_weighted_mean(Media.score)


def weighted_mean_votes_expr():
    """Per-anime relation-weighted mean vote count (`V_w`) — the displayed
    `avg_scored_by` and the confidence half of the ranking/pill metric."""
    return _relation_weighted_mean(Media.scored_by)


def _studio_condition(studio_names: list[str]):
    """The media is credited to at least one of `studio_names`. Membership test rather
    than a join so a media matching several of the selected studios doesn't fan out
    into duplicate rows."""
    return Media.id.in_(
        select(MediaStudio.media_id)
        .join(MediaStudio.studio)
        .where(Studio.name.in_(studio_names))
    )


def _parse_season_filters(anime_season: list[str]) -> list[tuple]:
    """Parse 'Season Year' strings into (year, SeasonType) tuples."""
    filter_pairs = []
    for part in anime_season:
        try:
            season, year = part.split(" ", 1)
            filter_pairs.append((int(year), SeasonType[season]))
        except (ValueError, KeyError):
            logger.warning("Ignoring malformed anime_season filter: %s", part)
    return filter_pairs


def _build_categorical_conditions(
    filters: MediaSearchFilters, *, for_anime: bool = False,
) -> list:
    """Build WHERE conditions for categorical media filters.

    `for_anime=True` excludes `age_rating` and `airing_status` — those move
    to HAVING-clause aggregations in `apply_anime_having_filters` so the
    filter matches the card's derived display value (max age across media,
    priority-collapsed airing status) instead of the any-media WHERE
    semantics that media-view search uses.
    """
    conditions = []
    if filters.media_type:
        conditions.append(Media.media_type.in_(filters.media_type))
    if filters.relation_type:
        conditions.append(Media.relation_type.in_(filters.relation_type))
    if not for_anime and filters.age_rating:
        conditions.append(Media.age_rating.in_(filters.age_rating))
    if not for_anime and filters.airing_status:
        conditions.append(Media.airing_status.in_(filters.airing_status))
    if filters.original_source:
        conditions.append(Media.original_source.in_(filters.original_source))
    if filters.anime_season:
        filter_pairs = _parse_season_filters(filters.anime_season)
        if filter_pairs:
            conditions.append(
                tuple_(Media.anime_season_year, Media.anime_season_name).in_(filter_pairs)
            )
    return conditions


def apply_media_filters(stmt, filters: MediaSearchFilters):
    """Apply media metadata filters (genre, studio, scores, etc.) to a query.
    The statement must already have Media accessible (via select or join)."""

    # Genre filter: require media to have ALL specified genres
    if filters.genre_name:
        unique_genres = set(filters.genre_name)
        subquery = (
            select(Media.id)
            .join(Media.media_genre)
            .join(MediaGenre.genre)
            .where(Genre.name.in_(unique_genres))
            .group_by(Media.id)
            .having(func.count(distinct(Genre.id)) >= len(unique_genres))
        ).subquery()
        stmt = stmt.where(Media.id.in_(select(subquery.c.id)))

    if filters.studio_name:
        stmt = stmt.where(_studio_condition(filters.studio_name))

    conditions = _build_categorical_conditions(filters)

    if filters.score_min is not None:
        conditions.append(Media.score.isnot(None) & (Media.score >= filters.score_min))
    if filters.score_max is not None:
        conditions.append(Media.score.isnot(None) & (Media.score <= filters.score_max))
    if filters.scored_by_min is not None:
        conditions.append(Media.scored_by >= filters.scored_by_min)
    if filters.scored_by_max is not None:
        conditions.append(Media.scored_by <= filters.scored_by_max)
    if filters.episodes_min is not None:
        conditions.append(Media.episodes.isnot(None) & (Media.episodes >= filters.episodes_min))
    if filters.episodes_max is not None:
        conditions.append(Media.episodes.isnot(None) & (Media.episodes <= filters.episodes_max))
    if filters.duration_per_episode_min is not None:
        conditions.append(
            Media.duration_seconds.isnot(None) & (Media.duration_seconds >= filters.duration_per_episode_min)
        )
    if filters.duration_per_episode_max is not None:
        conditions.append(
            Media.duration_seconds.isnot(None) & (Media.duration_seconds <= filters.duration_per_episode_max)
        )
    if filters.total_watch_time_min is not None:
        conditions.append(
            Media.total_watch_time.isnot(None) & (Media.total_watch_time >= filters.total_watch_time_min)
        )
    if filters.total_watch_time_max is not None:
        conditions.append(
            Media.total_watch_time.isnot(None) & (Media.total_watch_time <= filters.total_watch_time_max)
        )

    if conditions:
        stmt = stmt.where(and_(*conditions))

    return stmt


def anime_genre_majority_relation(genre_names: list[str] | None = None):
    """The `(anime_id, genre_name)` pairs where that genre is carried by a
    MAJORITY of the anime's media (`genre_count * 2 > total`) — a subquery.

    **Single source of the majority rule**, because two features depend on it
    agreeing with itself: the anime-view genre dropdown offers exactly the genres
    that can pass (`filter_service._get_anime_majority_genres` projects
    `DISTINCT genre_name` from here), and the search filter tests membership
    (`_anime_genre_majority_condition` below). Written twice, a threshold change
    would silently offer genres in the dropdown that the filter then rejects —
    an empty result page with no explanation.

    `genre_names` narrows the scan when the caller knows which genres it cares
    about; the dropdown passes None and takes them all.

    The denominator is the anime's FULL media count, deliberately unfiltered: the
    majority a user means when picking a genre is "most of this anime", not "most
    of whatever survived my other filters". Pinned by
    `test_genre_majority_denominator_survives_a_pre_filter`.
    """
    genre_counts = select(
        Media.anime_id.label("anime_id"),
        Genre.name.label("genre_name"),
        func.count(Media.id).label("genre_count"),
    ).join(MediaGenre, MediaGenre.media_id == Media.id).join(
        Genre, Genre.id == MediaGenre.genre_id
    )
    if genre_names:
        genre_counts = genre_counts.where(Genre.name.in_(set(genre_names)))
    genre_counts_sq = genre_counts.group_by(Media.anime_id, Genre.name).subquery()

    media_totals = (
        select(
            Media.anime_id.label("anime_id"),
            func.count(Media.id).label("total"),
        )
        .group_by(Media.anime_id)
    ).subquery()

    return (
        select(genre_counts_sq.c.anime_id, genre_counts_sq.c.genre_name)
        .join(media_totals, media_totals.c.anime_id == genre_counts_sq.c.anime_id)
        .where(genre_counts_sq.c.genre_count * 2 > media_totals.c.total)
    ).subquery()


def _anime_genre_majority_condition(genre_names: list[str]):
    """Anime clearing the majority bar on EVERY selected genre.

    One non-correlated pass over `anime_genre_majority_relation`: count each
    anime's surviving genres and require all N. The alternative shape — one
    correlated majority-subquery per genre — grows superlinearly, since each
    added genre both adds a SubPlan and widens the set every existing SubPlan is
    re-evaluated over, and this fires on ticking genre chips.
    """
    unique_genres = set(genre_names)
    majority = anime_genre_majority_relation(genre_names)
    qualifying = (
        select(majority.c.anime_id)
        .group_by(majority.c.anime_id)
        .having(func.count() == len(unique_genres))
    )
    return Anime.id.in_(qualifying)


def apply_anime_pre_filters(stmt, filters: MediaSearchFilters):
    """Select WHICH ANIME qualify. Two independent conditions, both selecting
    anime rather than narrowing the grouped media rows:

    - Categorical + studio, with 'any media matches' semantics — an anime is by
      studio X / of type TV when at least one of its media is. These share ONE
      subquery, so they must hold for the SAME media row (studio X + type TV
      means one media is a TV by X), matching media-level semantics.
    - Genre majority, which gets its own subquery precisely because it is NOT a
      same-media-row question — it's an aggregate over the anime's whole media
      set (see `_anime_genre_majority_condition`).

    Range, age_rating and airing_status filters are excluded here; they use
    HAVING aggregations that mirror the anime card's derived display values.

    Selecting anime rather than filtering the grouped media rows keeps the aggregates
    (`avg_score`/`avg_scored_by`/`total_episodes`/`media_count` and every HAVING
    filter) over the anime's full media set, so the shown score and the ordering
    derived from it are filter-independent — see
    compound-docs/2026-07-19-anime-score-main-only.md.
    """
    conditions = _build_categorical_conditions(filters, for_anime=True)
    if filters.studio_name:
        conditions.append(_studio_condition(filters.studio_name))

    if conditions:
        stmt = stmt.where(
            Anime.id.in_(select(Media.anime_id).where(and_(*conditions)))
        )

    if filters.genre_name:
        stmt = stmt.where(_anime_genre_majority_condition(filters.genre_name))

    return stmt


def apply_anime_having_filters(stmt, filters: MediaSearchFilters, agg_columns: dict):
    """Apply HAVING-clause filters on aggregated values for anime-level search.
    agg_columns maps field names to SQLAlchemy aggregate column expressions.

    Genre is NOT here — it's a majority test over the anime's media set, which
    `apply_anime_pre_filters` answers in one non-correlated pass."""
    conditions = []

    if filters.score_min is not None:
        conditions.append(agg_columns["avg_score"].isnot(None) & (agg_columns["avg_score"] >= filters.score_min))
    if filters.score_max is not None:
        conditions.append(agg_columns["avg_score"].isnot(None) & (agg_columns["avg_score"] <= filters.score_max))
    if filters.scored_by_min is not None:
        conditions.append(agg_columns["avg_scored_by"] >= filters.scored_by_min)
    if filters.scored_by_max is not None:
        conditions.append(agg_columns["avg_scored_by"] <= filters.scored_by_max)
    if filters.episodes_min is not None:
        conditions.append(agg_columns["total_episodes"].isnot(None) & (agg_columns["total_episodes"] >= filters.episodes_min))
    if filters.episodes_max is not None:
        conditions.append(agg_columns["total_episodes"].isnot(None) & (agg_columns["total_episodes"] <= filters.episodes_max))
    if filters.total_watch_time_min is not None:
        conditions.append(agg_columns["total_watch_time"].isnot(None) & (agg_columns["total_watch_time"] >= filters.total_watch_time_min))
    if filters.total_watch_time_max is not None:
        conditions.append(agg_columns["total_watch_time"].isnot(None) & (agg_columns["total_watch_time"] <= filters.total_watch_time_max))

    # Age-rating filter: compare against MAX(media.age_rating_numeric), the
    # same aggregation `_compute_anime_aggregates` uses for the card's
    # displayed age. A mixed-rating anime (e.g. G main + R side-story)
    # surfaces under R, not G, because the card surfaces under R.
    if filters.age_rating:
        tiers = [AGE_RATING_TIERS[rating] for rating in filters.age_rating]
        conditions.append(func.max(Media.age_rating_numeric).in_(tiers))

    # Airing-status filter: reproduce `_compute_airing_status`'s priority
    # ladder (Currently → Finished → Not yet aired) in SQL, then check
    # membership. Without this, an anime with one Currently-Airing media
    # and one Finished side-story would show up when the user filters
    # "Finished" — the WHERE-based any-media match wouldn't respect the
    # card's collapsed status.
    if filters.airing_status:
        # Mirror `_compute_airing_status` in anime_search_service.py: the
        # card collapses to Currently → Finished → Not yet aired by
        # priority. Filter against that derived value, not any-media
        # membership, so a Currently-Airing anime with a Finished side-
        # story doesn't surface under the "Finished" filter.
        has_current = func.bool_or(Media.airing_status == AIRING_STATUS_CURRENTLY_AIRING)
        has_finished = func.bool_or(Media.airing_status == AIRING_STATUS_FINISHED_AIRING)
        has_upcoming = func.bool_or(Media.airing_status == AIRING_STATUS_NOT_YET_AIRED)
        card_status = case(
            (has_current, AIRING_STATUS_CURRENTLY_AIRING),
            (has_finished, AIRING_STATUS_FINISHED_AIRING),
            (has_upcoming, AIRING_STATUS_NOT_YET_AIRED),
            else_=None,
        )
        conditions.append(card_status.in_(filters.airing_status))

    if conditions:
        stmt = stmt.having(and_(*conditions))

    return stmt


# The fuzzy tier's thresholds, strictest first — `fetch_search_results` tries each
# in turn.
#
# word_similarity compares the query's trigrams with the best contiguous stretch
# of the title's, as shared / (query ∪ stretch). A typo at the end of a word costs
# only the trigrams it breaks ("frieran" → Frieren, 5/8); a letter dropped mid-word
# also pays for the title's trigrams between the two halves ("friren" → 5/10).
# Partial-word noise lands at exactly 3/5 ("jojo" → Evangelion), so 0.61 keeps it
# out and admits end-of-word typos. It cannot be written `> 0.6`: word_similarity
# returns float4, and 0.6f promotes to 0.6000000238. Mid-word typos land among the
# noise, hence the 0.5 fallback. The calibration study is in
# compound-docs/2026-10-07-v0.16.0-search-rework.md — re-measure before moving
# either.
TITLE_MATCH_THRESHOLDS = (0.61, 0.5)


def _escape_like(text: str) -> str:
    """Escape SQL LIKE wildcards so user-supplied query characters match
    literally. We use `\\` as the escape character (matching the
    `escape="\\"` passed to `ilike`)."""
    return text.replace("\\", "\\\\").replace("%", "\\%").replace("_", "\\_")


def title_match_score(query: str, model: type[Anime] | type[Media]):
    """How well `query` matches the best of `model`'s title variants. The synonyms
    (`other_names`, a JSONB list) are matched as one JSON string, so a single
    ilike / word_similarity covers every synonym without unnesting the list.

    A substring hit scores `1 + similarity`, a fuzzy one its `word_similarity`
    (< 1 unless every query trigram is present), so a substring hit outranks any
    fuzzy hit, and among substring hits an exact title outranks a longer one that
    merely contains it. NULL variants drop out of GREATEST.

    There is no trigram index, so every variant is scored on every row and the cost
    grows linearly with the catalogue — the measured figure is in
    compound-docs/2026-10-07-v0.16.0-search-rework.md. A GIN `gin_trgm_ops` index
    plus a `%>` candidate pre-filter is the upgrade when that starts to matter."""
    pattern = f"%{_escape_like(query)}%"
    variants = (model.title, model.name_eng, model.name_jap, cast(model.other_names, Text))
    return func.greatest(*(
        case(
            (col.ilike(pattern, escape="\\"), 1 + func.similarity(query, col)),
            # Argument order matters: the short query first, the long title second.
            else_=func.word_similarity(query, col),
        )
        for col in variants
    ))


async def fetch_search_results(
    db: AsyncSession, stmt, title_match=None, *, having: bool = False,
) -> list:
    """Every row's first column, through the threshold fallback for a title search
    (`title_match` set).

    A retry rather than one query at the loosest threshold trimmed afterwards: the
    trim is only correct while the match is the primary sort key. `having` for a
    grouped statement whose match is an aggregate."""
    if title_match is None:
        return list((await db.execute(stmt)).scalars().all())
    restrict = stmt.having if having else stmt.where
    rows: list = []
    for threshold in TITLE_MATCH_THRESHOLDS:
        rows = list((await db.execute(restrict(title_match >= threshold))).scalars().all())
        if rows:
            break
    return rows


def apply_vector_ordering(
    stmt,
    search_type: SearchType,
    query_embedding,
    *,
    extra_columns: dict | None = None,
):
    """Order by cosine distance to the query embedding.

    `extra_columns` registers additional `search_type → embedding column`
    mappings (e.g., `RATING_NOTES → RatingSearch.note_embedding`).
    """
    columns = {**_VECTOR_COLUMNS, **(extra_columns or {})}
    column = columns.get(search_type)
    if column is None:
        logger.warning("No embedding column for search_type=%s; results will not be relevance-ordered", search_type)
        return stmt

    return stmt.order_by(func.cosine_distance(column, cast(query_embedding, Vector)))
