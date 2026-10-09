import logging
import re
from datetime import UTC, date, datetime

from sqlalchemy import (
    Float,
    Text,
    and_,
    asc,
    case,
    cast,
    desc,
    distinct,
    false,
    func,
    or_,
    select,
    tuple_,
)
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import aliased

from app.models.anime import Anime
from app.models.genre import Genre
from app.models.media import (
    AGE_RATING_TIERS,
    AIRING_STATUS_CURRENTLY_AIRING,
    AIRING_STATUS_FINISHED_AIRING,
    AIRING_STATUS_NOT_YET_AIRED,
    MAIN_STORY_RELATIONS,
    RELATION_SCORE_WEIGHTS,
    SEASON_ORDER,
    Media,
    SeasonType,
)
from app.models.media_genre import MediaGenre
from app.models.media_search import MediaSearch
from app.models.media_studio import MediaStudio
from app.models.studio import Studio
from app.models.user_settings import NameLanguage
from app.schemas.media_filter_schema import (
    CatalogueSearchFilters,
    MatchMode,
    MediaSearchFilters,
    SortDir,
    SortKey,
)

logger = logging.getLogger(__name__)


def weighted_score_expr(score, scored_by):
    """Confidence-weighted MAL score `score * log10(scored_by + 1)` — log10 (not
    ln) dampens the vote-count weight so a very popular but mediocre title can't
    outrank a higher-scored niche one. Single source of truth for the SQL form (the
    Python twin is `scrape_dispatcher._weighted_score`). `score` / `scored_by` may be
    plain columns (per-media, media DAOs) or the per-anime weighted means
    (`weighted_mean_score_expr` / `weighted_mean_votes_expr`).

    Float8 `log10`, the C function the twin's `math.log10` calls —
    `test_weighted_score_matches_python_twin` guards the equivalence. Not numeric
    `log(10, x)`: it costs ~60x more per row, enough to dominate every ordering by
    score and both badges (measured in
    compound-docs/2026-10-07-v0.16.0-search-rework.md).

    Computed per query over the whole catalogue. Past ~50k media, store it: a
    generated `media.weighted_score` column with an index, and a per-anime aggregate
    kept current by every write that changes an anime's media or their scores."""
    return score * func.log10(cast(scored_by + 1, Float))


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
    return num / func.nullif(den, 0.0)


def weighted_mean_score_expr():
    """Per-anime relation-weighted mean MAL score (`S_w`) — the displayed
    `avg_score` and the score half of the ranking/pill metric."""
    return _relation_weighted_mean(Media.score)


def weighted_mean_votes_expr():
    """Per-anime relation-weighted mean vote count (`V_w`) — the displayed
    `avg_scored_by` and the confidence half of the ranking/pill metric."""
    return _relation_weighted_mean(Media.scored_by)


def top_percent_ranking(*, per_anime: bool):
    """`(id, top_percent)` for every scored anime or media: the "Top N%" badge, ranked
    by `weighted_score_expr` over the whole catalogue (per anime, its relation-weighted
    means), and unfiltered, so N% is the same figure whatever else a search selects.

    `top_percent` is the rank as a percentage of the scored rows, rounded up — ties
    share their best rank, and the worst row reads 100.

    `rank()` rather than a count of the better rows, which would spare one badge its
    sort: the filter needs every row's rank."""
    if per_anime:
        mean_score = weighted_mean_score_expr()
        scored = (
            select(
                Media.anime_id.label("id"),
                weighted_score_expr(mean_score, weighted_mean_votes_expr()).label("metric"),
            )
            .group_by(Media.anime_id)
            .having(mean_score.is_not(None))
        )
    else:
        scored = select(
            Media.id.label("id"), weighted_score_expr(Media.score, Media.scored_by).label("metric"),
        ).where(Media.score.is_not(None))
    population = scored.subquery()
    rank = func.rank().over(order_by=population.c.metric.desc())
    total = func.count().over()
    return select(population.c.id, ((rank * 100 + total - 1) // total).label("top_percent")).subquery()


def _top_percent_ids(top_percent: int, *, per_anime: bool):
    ranking = top_percent_ranking(per_anime=per_anime)
    return select(ranking.c.id).where(ranking.c.top_percent <= top_percent)


def _needed(names: list[str], mode: MatchMode) -> int:
    """How many of the selected `names` a row must carry under `mode`."""
    return len(set(names)) if mode == MatchMode.ALL else 1


def _carrying_studios(credits, key, studio_names: list[str], mode: MatchMode):
    """`credits` — a select over `MediaStudio` rows — grouped by `key`, keeping the
    groups credited to one (`any`) or every (`all`) of `studio_names`. Used as a
    membership test rather than a join, so a row matching several of the selected
    studios doesn't fan out into duplicates."""
    return (
        credits.join(Studio, Studio.id == MediaStudio.studio_id)
        .where(Studio.name.in_(studio_names))
        .group_by(key)
        .having(func.count(distinct(Studio.id)) >= _needed(studio_names, mode))
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

    # Genre filter: the media's own genres, where the anime grain counts a majority
    if filters.genre_name:
        subquery = (
            select(Media.id)
            .join(Media.media_genre)
            .join(MediaGenre.genre)
            .where(Genre.name.in_(filters.genre_name))
            .group_by(Media.id)
            .having(func.count(distinct(Genre.id)) >= _needed(filters.genre_name, filters.genre_mode))
        ).subquery()
        stmt = stmt.where(Media.id.in_(select(subquery.c.id)))

    if filters.studio_name:
        stmt = stmt.where(Media.id.in_(_carrying_studios(
            select(MediaStudio.media_id), MediaStudio.media_id, filters.studio_name, filters.studio_mode,
        )))

    if filters.top_percent is not None:
        stmt = stmt.where(Media.id.in_(_top_percent_ids(filters.top_percent, per_anime=False)))

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


def _anime_genre_majority_condition(genre_names: list[str], mode: MatchMode):
    """Anime clearing the majority bar on every (`all`) or one (`any`) selected genre.

    One non-correlated pass over `anime_genre_majority_relation`: count each
    anime's surviving genres and require all N, or one. The alternative shape — one
    correlated majority-subquery per genre — grows superlinearly, since each
    added genre both adds a SubPlan and widens the set every existing SubPlan is
    re-evaluated over, and this fires on ticking genre chips.
    """
    majority = anime_genre_majority_relation(genre_names)
    qualifying = (
        select(majority.c.anime_id)
        .group_by(majority.c.anime_id)
        .having(func.count() >= _needed(genre_names, mode))
    )
    return Anime.id.in_(qualifying)


# A main-story media not aired yet: what the release sort counts as an announcement and
# what `upcoming_main` keeps, which "closest to release" needs to agree.
ANNOUNCED_MAIN_STORY = Media.relation_type.in_(MAIN_STORY_RELATIONS) & (
    Media.airing_status == AIRING_STATUS_NOT_YET_AIRED
)


def upcoming_main_media():
    """The media is an announced main-story entry of an anime that has aired content:
    `upcoming_main` at the media grain, and the anime grain keeps the anime holding
    one. Why main story only, unlike the card's `has_upcoming`
    (`anime_search_service._compute_airing_status`): docs/features/search.md.

    Aired content is the card's Currently/Finished pair, not `Media.is_rateable`, so
    the two agree on any other status."""
    aired = aliased(Media)
    return and_(
        ANNOUNCED_MAIN_STORY,
        Media.anime_id.in_(
            select(aired.anime_id).where(
                aired.airing_status.in_((AIRING_STATUS_CURRENTLY_AIRING, AIRING_STATUS_FINISHED_AIRING))
            )
        ),
    )


def apply_anime_pre_filters(stmt, filters: CatalogueSearchFilters):
    """Select WHICH ANIME qualify. Independent conditions, all selecting anime rather
    than narrowing the grouped media rows:

    - Categorical + studio, with 'any media matches' semantics — an anime is of
      type TV when at least one of its media is. These share ONE subquery, so the
      categorical conditions and the studios hold for the same media: studio X +
      type TV means one media is a TV by X. Coupling both modes keeps them equal for
      a single studio.
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
    matching = select(Media.anime_id).where(*conditions)
    if filters.studio_name:
        matching = _carrying_studios(
            matching.join(MediaStudio, MediaStudio.media_id == Media.id),
            Media.anime_id, filters.studio_name, filters.studio_mode,
        )
    if filters.studio_name or conditions:
        stmt = stmt.where(Anime.id.in_(matching))

    if filters.genre_name:
        stmt = stmt.where(_anime_genre_majority_condition(filters.genre_name, filters.genre_mode))

    if filters.top_percent is not None:
        stmt = stmt.where(Anime.id.in_(_top_percent_ids(filters.top_percent, per_anime=True)))

    if filters.upcoming_main:
        stmt = stmt.where(Anime.id.in_(select(Media.anime_id).where(upcoming_main_media())))

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


# The fuzzy tier's thresholds, strictest first — `title_match_passes` makes each a
# pass of its own, which `fetch_search_results` tries in turn.
#
# word_similarity compares the query's trigrams with the best contiguous stretch
# of the title's, as shared / (query ∪ stretch). A typo at the end of a word costs
# only the trigrams it breaks ("frieran" → Frieren, 5/8); a letter dropped mid-word
# also pays for the title's trigrams between the two halves ("friren" → 5/10).
# Partial-word noise lands at exactly 3/5 ("jojo" → Evangelion), so 0.61 keeps it
# out and admits end-of-word typos. It cannot be written `> 0.6`: word_similarity
# returns float4, and 0.6f promotes to 0.6000000238. Mid-word typos land among the
# noise, hence the 0.5 fallback. The strict one also gates the literal-first
# searches' typo retry (`literal_matches`). The calibration study is in
# compound-docs/2026-10-07-v0.16.0-search-rework.md — re-measure every search before
# moving either.
TITLE_MATCH_THRESHOLDS = (0.61, 0.5)


def _escape_like(text: str) -> str:
    """Escape SQL LIKE wildcards so user-supplied query characters match
    literally. We use `\\` as the escape character (matching the
    `escape="\\"` passed to `ilike`)."""
    return text.replace("\\", "\\\\").replace("%", "\\%").replace("_", "\\_")


def _title_variants(model: type[Anime] | type[Media]) -> tuple:
    """Every title a row goes by: romaji, English, Japanese, and the synonyms
    (`other_names`, a JSONB list) as one JSON string, so a single ilike,
    word_similarity or regex covers every synonym without unnesting the list. The
    embeddings' twins are `media_search_service.media_title_texts` and
    `anime_search_service.anime_title_texts`."""
    return (model.title, model.name_eng, model.name_jap, cast(model.other_names, Text))


def title_match_score(query: str, model: type[Anime] | type[Media]):
    """How well `query` matches the best of `model`'s `_title_variants`.

    A substring hit scores `1 + similarity`, a fuzzy one its `word_similarity`
    (< 1 unless every query trigram is present), so a substring hit outranks any
    fuzzy hit, and among substring hits an exact title outranks a longer one that
    merely contains it. NULL variants drop out of GREATEST.

    There is no trigram index, so every variant is scored on every row and the cost
    grows linearly with the catalogue — the measured figure is in
    compound-docs/2026-10-07-v0.16.0-search-rework.md. A GIN `gin_trgm_ops` index
    plus a `%>` candidate pre-filter is the upgrade when that starts to matter."""
    pattern = f"%{_escape_like(query)}%"
    return func.greatest(*(
        case(
            (col.ilike(pattern, escape="\\"), 1 + func.similarity(query, col)),
            # Argument order matters: the short query first, the long title second.
            else_=func.word_similarity(query, col),
        )
        for col in _title_variants(model)
    ))


def title_match_passes(stmt, title_match, *, having: bool = False) -> list:
    """`stmt` restricted to each of `TITLE_MATCH_THRESHOLDS`, strictest first, for
    `fetch_search_results`. `having` for a grouped statement whose match is an
    aggregate."""
    restrict = stmt.having if having else stmt.where
    return [restrict(title_match >= threshold) for threshold in TITLE_MATCH_THRESHOLDS]


# How far below the searched population's mean distance to the query a semantic hit
# must sit (`description_cutoff`, `note_cutoff`); why relative is in
# docs/features/search.md. Specific to the embedding model: the calibration studies are
# in compound-docs/2026-10-07-v0.16.0-search-rework.md and
# compound-docs/2026-10-09-v0.16.1-search-ui.md — re-measure every population on a model
# change.
SEMANTIC_MARGIN = 0.30


def _description_distance(query_embedding):
    """Cosine distance from the query to the description embedding; NULL for a media
    without a description, which is never a semantic hit (docs/features/search.md)."""
    return case((Media.description != "", MediaSearch.description_embedding.cosine_distance(query_embedding)))


def description_cutoff(query_embedding):
    """The largest distance a semantic hit may have: the mean distance to the query
    over the whole, unfiltered catalogue, less `SEMANTIC_MARGIN`. Its explicit FROM
    keeps SQLAlchemy from correlating it with the outer row, which would make the mean
    that row's own distance."""
    mean = (
        select(func.avg(_description_distance(query_embedding)))
        .select_from(MediaSearch)
        .join(Media, Media.id == MediaSearch.media_id)
        .scalar_subquery()
    )
    return mean - SEMANTIC_MARGIN


def literal_matches(query: str, text) -> list:
    """The literal tier's tests over `text`, strict then fuzzy: every word of the
    query starts a word of it (a prefix, never an infix), or reaches the strict title
    threshold in `word_similarity`. Words are `\\w+` runs, so `\\m` + word needs no
    regex escaping; a query without any has no literal tier."""
    words = re.findall(r"\w+", query)
    if not words:
        return [false()]
    return [
        and_(*(text.regexp_match(rf"\m{word}", flags="i") for word in words)),
        and_(*(func.word_similarity(word, text) >= TITLE_MATCH_THRESHOLDS[0] for word in words)),
    ]


def match_passes(stmt, literals: list, distance, cutoff, *, having: bool, aggregate) -> list:
    """Literal-first search, one pass per literal test for `fetch_search_results`:
    literal hits first, then semantic hits down to `cutoff`, each nearest first.

    `having` for the anime grain's grouped statement: `bool_or` over the literal
    tests, `aggregate` over the distance."""
    pk, restrict = Media.id, stmt.where
    if having:
        distance, pk, restrict = aggregate(distance), Anime.id, stmt.having
        literals = [func.bool_or(literal) for literal in literals]
    return [
        restrict(or_(literal, distance <= cutoff)).order_by(literal.desc(), distance, pk)
        for literal in literals
    ]


def description_passes(stmt, query: str, query_embedding, *, having: bool = False) -> list:
    """Description search through `match_passes`, over the text the description
    embedding encodes: the media's titles and description. Outer join, so a media
    without an embedding can still be a literal hit. The anime grain averages its
    media's distances; why is in docs/features/search.md."""
    text = func.concat_ws(" ", *_title_variants(Media), Media.description)
    return match_passes(
        stmt.outerjoin(MediaSearch, MediaSearch.media_id == Media.id),
        literal_matches(query, text),
        _description_distance(query_embedding),
        description_cutoff(query_embedding),
        having=having, aggregate=func.avg,
    )


# Sortable season key: `year * 10 + rank`, so (2026, Fall) > (2026, Summer) and
# (2027, Winter) > both with one integer comparison. The SQL twin of
# `filter_service.chronological_media_key`'s first two components, and what every SQL
# ordering by season reads.
#
# No `else_`: every SeasonType has a WHEN, and `check_season_parts_both_or_none` makes
# a year without a season unstorable, so no fallback is reachable. Defaulting to NULL
# rather than a rank of 0 is still the better shape for a season added to the enum
# later — it drops out of the MIN instead of sorting ahead of Winter. Unreachable
# today, so no test separates the two.
#
# Explicit WHEN comparisons, not the `case(mapping, value=...)` shorthand —
# rules/database.md.
SEASON_KEY = Media.anime_season_year * 10 + case(
    *[(Media.anime_season_name == season, rank) for season, rank in SEASON_ORDER.items()],
)

# Where the release sort puts an announcement that has no season yet: after every real
# season, since `check_season_year_4_digits` caps the year at 2200.
TBA_SEASON_KEY = 99_999


def _release_key(*, having: bool):
    """The release sort's key, per media or, with `having`, per anime: the timeline in
    docs/features/search.md#sorting."""
    unaired = Media.airing_status == AIRING_STATUS_NOT_YET_AIRED
    if not having:
        return func.coalesce(SEASON_KEY, case((unaired, TBA_SEASON_KEY)))
    main = Media.relation_type.in_(MAIN_STORY_RELATIONS)
    return func.coalesce(
        func.min(SEASON_KEY).filter(ANNOUNCED_MAIN_STORY),
        func.max(case((ANNOUNCED_MAIN_STORY & Media.anime_season_year.is_(None), TBA_SEASON_KEY))),
        func.max(SEASON_KEY).filter(main & ~unaired),
    )


def display_title(model: type[Anime] | type[Media], name_language: NameLanguage):
    """The title a card shows: the SQL twin of the frontend's `resolveTitle`, so the
    title sort orders what the card displays."""
    preferred = {NameLanguage.english: model.name_eng, NameLanguage.japanese: model.name_jap}.get(name_language)
    return model.title if preferred is None else func.coalesce(func.nullif(preferred, ""), model.title)


def utc_today() -> date:
    """The random sort's seed date; a function so a test can move it."""
    return datetime.now(UTC).date()


def sort_order(
    sort: SortKey, sort_dir: SortDir | None, name_language: NameLanguage, *, query: str,
    having: bool = False, your_rating=None,
) -> list | None:
    """ORDER BY for `sort` over Media rows, or over the anime grain's grouped rows with
    `having` (aggregates and Anime columns only, both valid under its GROUP BY).

    The key comes first, NULLS LAST in either direction, so an unscored or unseasoned
    row never leads an ascending list. Ties go to the weighted score, then to the PK in
    the sort's direction. That makes newest-first end `created_at DESC, …, id DESC`, as
    `recency_order` would. It doesn't go through that helper, which would put the PK
    straight after the timestamp: rows added in one transaction share `created_at`, and
    among them the better one should lead.

    RELEVANCE with a query returns None, so each pass keeps its own match order.

    YOUR_RATING orders by `your_rating`, which the DAO that joins the caller's ratings
    passes (docs/features/search.md, Personal filters and sort)."""
    if sort == SortKey.RELEVANCE:
        if query:
            return None
        sort_dir = None
    model: type[Anime] | type[Media] = Anime if having else Media
    if having:
        score, votes = weighted_mean_score_expr(), weighted_mean_votes_expr()
    else:
        score, votes = Media.score, Media.scored_by
    weighted = weighted_score_expr(score, votes)
    match sort:
        case SortKey.SCORE:
            key = score
        case SortKey.POPULARITY:
            key = votes
        case SortKey.ADDED:
            key = model.created_at
        case SortKey.RELEASE:
            key = _release_key(having=having)
        case SortKey.TITLE:
            key = display_title(model, name_language)
        case SortKey.RANDOM:
            key = func.md5(cast(model.uuid, Text) + utc_today().isoformat())
        case SortKey.YOUR_RATING:
            assert your_rating is not None
            key = your_rating
        case SortKey.TOP_RATED | SortKey.RELEVANCE:
            key = weighted
    ascending = sort_dir == SortDir.ASC if sort_dir else sort in (SortKey.TITLE, SortKey.RELEASE)
    direction = asc if ascending else desc
    return [direction(key).nulls_last(), weighted.desc().nulls_last(), direction(model.id)]


async def fetch_search_results(db: AsyncSession, *passes, order: list | None = None) -> list:
    """Every row's first column from the first of `passes` that returns any — the
    strict statement, then looser ones only while nothing has matched.

    `order`, a `sort_order` when given, replaces each pass's own: the passes decide which rows
    match, the sort only their order. Hence a retry rather than one query at the
    loosest test trimmed afterwards — the trim is only correct while the match is the
    primary sort key."""
    rows: list = []
    for stmt in passes:
        if order:
            stmt = stmt.order_by(None).order_by(*order)
        rows = list((await db.execute(stmt)).scalars().all())
        if rows:
            break
    return rows
