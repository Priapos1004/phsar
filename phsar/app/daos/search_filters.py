import logging

from pgvector.sqlalchemy import Vector
from sqlalchemy import and_, case, cast, distinct, func, select, tuple_

from app.models.genre import Genre
from app.models.media import AGE_RATING_MAP, Media, SeasonType
from app.models.media_genre import MediaGenre
from app.models.media_search import MediaSearch
from app.models.media_studio import MediaStudio
from app.models.studio import Studio
from app.schemas.media_filter_schema import MediaSearchFilters, SearchType
from app.services.relation_classifier import (
    AIRING_STATUS_CURRENTLY_AIRING,
    AIRING_STATUS_FINISHED_AIRING,
    AIRING_STATUS_NOT_YET_AIRED,
)

logger = logging.getLogger(__name__)

# Base mapping from search type to the embedding column used for cosine distance ordering
_VECTOR_COLUMNS = {
    SearchType.TITLE: MediaSearch.title_embedding,
    SearchType.DESCRIPTION: MediaSearch.description_embedding,
}


def weighted_score_expr(score, scored_by):
    """Confidence-weighted MAL score `score * log10(scored_by + 1)` — log10 (not
    ln) dampens the vote-count weight so a very popular but mediocre title can't
    outrank a higher-scored niche one. Single source of truth for the SQL form,
    shared by media + anime search ranking and the `score_top_percent` percentile
    DAOs (the Python twin is `scrape_dispatcher._weighted_score`). `score` /
    `scored_by` may be plain columns (per-media) or aggregates (per-anime avg).

    The base is passed explicitly (`log(10, x)`) rather than relying on
    Postgres's single-arg `log()` defaulting to base 10, so the SQL stays
    numerically locked to the Python twin's `math.log10` even if the dialect
    changes — `test_weighted_score_matches_python_twin` guards the equivalence."""
    return score * func.log(10, scored_by + 1)


def _apply_studio_filter(stmt, studio_names: list[str]):
    """Subquery-based studio filter to avoid duplicate rows from multiple matching studios."""
    studio_subquery = (
        select(MediaStudio.media_id)
        .join(MediaStudio.studio)
        .where(Studio.name.in_(studio_names))
    ).subquery()
    return stmt.where(Media.id.in_(select(studio_subquery.c.media_id)))


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
    if filters.anime_season:
        filter_pairs = _parse_season_filters(filters.anime_season)
        if filter_pairs:
            conditions.append(
                tuple_(Media.anime_season_year, Media.anime_season_name).in_(filter_pairs)
            )
    return conditions


def _age_rating_text_to_numerics(text_ratings: list[str]) -> list[int]:
    """Map MAL `age_rating` text strings to their numeric tier using the
    same prefix lookup the `Media.age_rating_numeric` hybrid uses. Lets the
    anime-view filter compare against `MAX(age_rating_numeric)` (the card's
    derivation) without round-tripping back to text."""
    results: list[int] = []
    for text in text_ratings:
        normalized = text.strip()
        for prefix, value in AGE_RATING_MAP:
            if normalized.startswith(prefix):
                results.append(value)
                break
    return results


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
        stmt = _apply_studio_filter(stmt, filters.studio_name)

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


def apply_anime_pre_filters(stmt, filters: MediaSearchFilters):
    """Apply WHERE-clause filters with 'any' semantics for anime-level search.
    These narrow which media rows enter the GROUP BY. Genre, range, age_rating,
    and airing_status filters are excluded — they use HAVING aggregations that
    mirror the anime card's derived display values instead."""

    if filters.studio_name:
        stmt = _apply_studio_filter(stmt, filters.studio_name)

    conditions = _build_categorical_conditions(filters, for_anime=True)

    if conditions:
        stmt = stmt.where(and_(*conditions))

    return stmt


def apply_anime_having_filters(stmt, filters: MediaSearchFilters, agg_columns: dict):
    """Apply HAVING-clause filters on aggregated values for anime-level search.
    agg_columns maps field names to SQLAlchemy aggregate column expressions."""
    # Deferred import to avoid circular dependency: search_filters <- anime_dao <- search_filters
    from app.models.anime import Anime

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

    # Genre majority filter: for each selected genre, a correlated subquery checks
    # if >50% of the anime's media have that genre. This mirrors the threshold in
    # filter_service._get_anime_majority_genres, which uses the same formula to
    # determine which genres appear in the dropdown.
    if filters.genre_name:
        for genre_name in filters.genre_name:
            genre_count_subq = (
                select(func.count(Media.id))
                .join(Media.media_genre)
                .join(MediaGenre.genre)
                .where(Media.anime_id == Anime.id)
                .where(Genre.name == genre_name)
                .correlate(Anime)
                .scalar_subquery()
            )
            conditions.append(genre_count_subq * 2 > agg_columns["media_count"])

    # Age-rating filter: compare against MAX(media.age_rating_numeric), the
    # same aggregation `_compute_anime_aggregates` uses for the card's
    # displayed age. A mixed-rating anime (e.g. G main + R side-story)
    # surfaces under R, not G, because the card surfaces under R.
    if filters.age_rating:
        numerics = _age_rating_text_to_numerics(filters.age_rating)
        if numerics:
            conditions.append(func.max(Media.age_rating_numeric).in_(numerics))

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


# Two-tier title-match bonus subtracted from cosine_distance. Without
# either, pure embedding distance ranks thematically-similar shows
# above titles that literally contain the user's query — e.g. "Lord of"
# against the catalog can promote "Overlord" over "Lord of Mysteries"
# because the embeddings cluster on theme, not literal token match.
#
# Cosine distance ranges roughly 0.2-1.0 for mid-cluster results. The
# substring bonus closes a ~0.2 cosine gap on an exact match; the
# fuzzy bonus peaks at a similar magnitude when word_similarity is
# perfect, so the two tiers reach roughly the same maximum lift but
# via different signals.
# - SUBSTRING (case-insensitive ilike): exact contiguous match wins a
#   flat bonus. Tight signal, low false-positive risk.
# - FUZZY (pg_trgm word_similarity above a threshold): catches typos,
#   partial spellings, and transposed letters the substring rule
#   misses ("lord of myst" or "lrod of myst" → "Lord of Mysteries").
#   word_similarity is used instead of plain similarity because the
#   query is usually a short phrase that fuzzy-matches part of a
#   longer title — plain similarity penalises the length mismatch and
#   buries partial matches. Threshold 0.4 filters most false positives
#   (probed against the dev catalog: unrelated short-query noise sits
#   around 0.43-0.44, true partial matches at 0.5+). Proportional
#   scaling above the threshold means borderline noise contributes
#   almost nothing while strong matches approach the substring bonus.
_TITLE_MATCH_BONUS_WEIGHT = 0.2
_TITLE_FUZZY_SIMILARITY_THRESHOLD = 0.4
_TITLE_FUZZY_BONUS_SCALER = 0.3  # (sim - threshold) * scaler; max ≈ 0.18 at sim=1.0


def _escape_like(text: str) -> str:
    """Escape SQL LIKE wildcards so user-supplied query characters match
    literally. We use `\\` as the escape character (matching the
    `escape="\\"` passed to `ilike`)."""
    return text.replace("\\", "\\\\").replace("%", "\\%").replace("_", "\\_")


def apply_vector_ordering(
    stmt,
    search_type: SearchType,
    query_embedding,
    *,
    query: str | None = None,
    title_columns: list | None = None,
    extra_columns: dict | None = None,
):
    """Apply cosine distance ordering for vector similarity search.

    `extra_columns` registers additional `search_type → embedding column`
    mappings (e.g., `RATING_NOTES → RatingSearch.note_embedding`).

    `query` + `title_columns` enable two literal-text bonuses on
    `SearchType.TITLE` (description and rating-notes search skip both
    — those queries are semantic, not literal):
    - Substring (`ilike '%query%'`): contributes `_TITLE_MATCH_BONUS_WEIGHT`
      per column when the column contains the raw query case-insensitively.
    - Fuzzy (`pg_trgm.similarity >= threshold`): contributes
      `_TITLE_FUZZY_BONUS_WEIGHT` per column above the similarity threshold.
      Catches typos / partial spellings the substring rule misses.

    Bonuses across columns AND across the two tiers sum, so an anime
    matching both `title` and `name_eng` and matching both literally and
    fuzzily gets the strongest boost.
    """
    columns = {**_VECTOR_COLUMNS, **(extra_columns or {})}
    column = columns.get(search_type)
    if column is None:
        logger.warning("No embedding column for search_type=%s; results will not be relevance-ordered", search_type)
        return stmt

    distance = func.cosine_distance(column, cast(query_embedding, Vector))

    if query and title_columns and search_type == SearchType.TITLE:
        pattern = f"%{_escape_like(query)}%"
        bonus_terms: list = []
        for col in title_columns:
            bonus_terms.append(case(
                (col.ilike(pattern, escape="\\"), _TITLE_MATCH_BONUS_WEIGHT),
                else_=0.0,
            ))
            # word_similarity(query, target) — argument order matters:
            # the SHORT query goes first, the LONG title second.
            sim = func.word_similarity(query, col)
            bonus_terms.append(case(
                (
                    sim >= _TITLE_FUZZY_SIMILARITY_THRESHOLD,
                    (sim - _TITLE_FUZZY_SIMILARITY_THRESHOLD) * _TITLE_FUZZY_BONUS_SCALER,
                ),
                else_=0.0,
            ))
        total_bonus = bonus_terms[0]
        for term in bonus_terms[1:]:
            total_bonus = total_bonus + term
        distance = distance - total_bonus

    return stmt.order_by(distance)
