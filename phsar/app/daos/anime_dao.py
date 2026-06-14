import logging
from typing import Any, NamedTuple
from uuid import UUID

from pgvector.sqlalchemy import Vector
from sqlalchemy import and_, case, cast, exists, func, or_, select, text
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import aliased, selectinload

from app.daos.base_mal_id_dao import MalIdDAO
from app.daos.search_filters import (
    apply_anime_having_filters,
    apply_anime_pre_filters,
    apply_vector_ordering,
)
from app.models.anime import Anime
from app.models.anime_freshness import AnimeFreshness
from app.models.anime_search import AnimeSearch
from app.models.media import Media, RelationType
from app.models.media_genre import MediaGenre
from app.models.media_search import MediaSearch
from app.models.media_studio import MediaStudio
from app.schemas.media_filter_schema import MediaSearchFilters, SearchType
from app.services.jikan_scraper import AIRING_STATUS_CURRENTLY_AIRING
from app.services.vector_embedding_service import generate_embedding

logger = logging.getLogger(__name__)

# Tier 3 of the nightly sweep: only weekly-probe franchises whose latest
# main media aired within this window. Older main-only franchises fall
# back to tier 4 (180-day long tail).
SWEEP_RECENT_MAIN_YEARS = 5


class _SweepTierPredicates(NamedTuple):
    airing_now: Any
    still_stabilizing: Any
    weekly_recent_main: Any
    long_tail: Any


def _sweep_tier_predicates(freshness_alias) -> _SweepTierPredicates:
    """Build the four sweep-tier predicates against the given freshness
    alias. Shared between `select_due_for_sweep` (OR'd to pick what's
    due) and `count_by_sweep_tier_priority` (priority-cascaded into
    mutually-exclusive buckets)."""
    last_checked = func.coalesce(freshness_alias.last_checked_at, Anime.created_at)
    stable = func.coalesce(freshness_alias.stable_check_count, 0)
    now = func.now()
    week_ago = now - text("interval '7 days'")
    six_mo_ago = now - text("interval '180 days'")
    recent_main_cutoff = now - text(f"interval '{SWEEP_RECENT_MAIN_YEARS} years'")

    airing_now = exists().where(
        and_(
            Media.anime_id == Anime.id,
            Media.airing_status == AIRING_STATUS_CURRENTLY_AIRING,
        )
    )
    recent_main = exists().where(
        and_(
            Media.anime_id == Anime.id,
            Media.relation_type == RelationType.Main,
            Media.aired_from >= recent_main_cutoff,
        )
    )
    return _SweepTierPredicates(
        airing_now=airing_now,
        still_stabilizing=stable < 3,
        weekly_recent_main=and_(last_checked < week_ago, recent_main),
        long_tail=last_checked < six_mo_ago,
    )


class AnimeDAO(MalIdDAO[Anime]):
    def __init__(self):
        super().__init__(Anime)

    @staticmethod
    def _anime_eager_options():
        """Shared eager-load options for anime with media, genres, and studios."""
        return [
            selectinload(Anime.media)
            .selectinload(Media.media_genre)
            .selectinload(MediaGenre.genre),
            selectinload(Anime.media)
            .selectinload(Media.media_studio)
            .selectinload(MediaStudio.studio),
        ]

    async def get_by_uuid_with_all_media(self, db: AsyncSession, uuid: UUID) -> Anime | None:
        """Fetch anime by UUID with all media eagerly loaded (including genres/studios per media)."""
        stmt = (
            select(Anime)
            .filter(Anime.uuid == uuid)
            .options(*self._anime_eager_options())
        )
        result = await db.execute(stmt)
        return result.scalars().first()

    async def get_by_media_mal_id_with_media(
        self, db: AsyncSession, media_mal_id: int,
    ) -> Anime | None:
        """Resolve a `Media.mal_id` back to its owning Anime, with
        `Anime.media` eager-loaded so callers (the orphan-side-story
        attach path in `scrape_dispatcher`) can read the parent's
        existing media set without a `lazy="raise"` fault."""
        stmt = (
            select(Anime)
            .join(Media, Media.anime_id == Anime.id)
            .where(Media.mal_id == media_mal_id)
            .options(selectinload(Anime.media))
        )
        return (await db.execute(stmt)).scalars().first()

    async def select_due_for_sweep(
        self, db: AsyncSession, limit: int,
    ) -> list[Anime]:
        """Anime due for the nightly update sweep, oldest-first.

        Four tiers OR'd together:
          1. Has a "Currently Airing" media — always due.
          2. stable_check_count < 3 — burn the initial stability sampling.
          3. Last checked > 7 days ago AND has a recent main media
             (aired_from within SWEEP_RECENT_MAIN_YEARS). Sequels
             announce off the main story; old main-only franchises don't
             warrant weekly cycles.
          4. Last checked > 180 days ago — long-tail safety net.

        LEFT JOIN against anime_freshness because the migration backfilled
        every existing row but a future code path could insert without one;
        the COALESCE expression powers the WHERE-clause staleness checks
        (long_tail / weekly_recent_main). ORDER BY uses raw
        `last_checked_at NULLS FIRST` instead — see the ordering comment
        below for why never-checked rows belong at the front, not at
        their created_at position.
        """
        af = aliased(AnimeFreshness)
        preds = _sweep_tier_predicates(af)

        stmt = (
            select(Anime)
            .outerjoin(af, af.anime_id == Anime.id)
            .where(or_(
                preds.airing_now,
                preds.still_stabilizing,
                preds.weekly_recent_main,
                preds.long_tail,
            ))
            # Primary order: `nullsfirst()` puts never-checked rows at the
            # front. A NULL last_checked_at is "maximum staleness from MAL's
            # perspective" — new anime (always due via tier 2) must survive
            # the LIMIT cap even when there's a 180-day stale backlog so the
            # 3-check stabilization sampling completes promptly.
            # Secondary: tiebreak by created_at so older catalog entries
            # win, not whichever anime.id happens to be lower (the
            # tiebreaker is only deterministic by accident under a
            # sequential PK).
            .order_by(
                af.last_checked_at.asc().nullsfirst(),
                Anime.created_at.asc(),
                Anime.id.asc(),
            )
            .options(
                selectinload(Anime.media).options(
                    selectinload(Media.freshness),
                    selectinload(Media.relation_edges),
                    # Genre + studio M2M needed by the metadata drift
                    # detectors in scrape_dispatcher — without these the
                    # drift compare trips `lazy="raise"`.
                    selectinload(Media.media_genre).selectinload(MediaGenre.genre),
                    selectinload(Media.media_studio).selectinload(MediaStudio.studio),
                ),
                selectinload(Anime.freshness),
            )
            .limit(limit)
        )
        result = await db.execute(stmt)
        return list(result.scalars().all())

    _TIER_BUCKETS: tuple[str, ...] = (
        "airing_now",
        "stabilizing",
        "weekly_recent_main",
        "long_tail",
        "not_currently_due",
    )

    async def count_by_sweep_tier_priority(
        self, db: AsyncSession,
    ) -> dict[str, int]:
        """5 mutually-exclusive bucket counts in priority cascade:
        airing_now > stabilizing > weekly_recent_main > long_tail >
        not_currently_due. Sum equals total anime count.

        Powers the admin Overview tier-breakdown card. Single GROUP BY
        on a CASE expression — the same predicates as select_due_for_sweep
        so the buckets match the selection logic exactly.
        """
        af = aliased(AnimeFreshness)
        preds = _sweep_tier_predicates(af)
        bucket = case(
            (preds.airing_now, "airing_now"),
            (preds.still_stabilizing, "stabilizing"),
            (preds.weekly_recent_main, "weekly_recent_main"),
            (preds.long_tail, "long_tail"),
            else_="not_currently_due",
        ).label("bucket")
        stmt = (
            select(bucket, func.count(Anime.id))
            .outerjoin(af, af.anime_id == Anime.id)
            .group_by(bucket)
        )
        rows = (await db.execute(stmt)).all()
        counts = {b: 0 for b in self._TIER_BUCKETS}
        for bucket_name, count in rows:
            counts[bucket_name] = count
        return counts

    async def list_recent(self, db: AsyncSession, limit: int = 10) -> list[Anime]:
        """Most-recently scraped anime, newest first. Powers the
        'recent additions' panel on /library/add."""
        stmt = (
            select(Anime)
            .order_by(Anime.created_at.desc())
            .limit(limit)
        )
        result = await db.execute(stmt)
        return list(result.scalars().all())

    async def search_anime_aggregated(
        self,
        db: AsyncSession,
        query: str,
        filters: MediaSearchFilters,
        search_type: SearchType,
        limit: int = 50,
    ) -> list[Anime]:
        """Anime search: aggregation query for filtering/ordering,
        then detail fetch for the matched anime.

        Returns Anime objects with eagerly loaded media/genres/studios,
        ordered by search relevance or weighted score."""

        # --- Phase A: Aggregation query (for filtering + ordering only) ---
        avg_score = func.avg(Media.score).label("avg_score")
        avg_scored_by = func.avg(Media.scored_by).label("avg_scored_by")
        total_episodes = func.sum(Media.episodes).label("total_episodes")
        total_watch_time = func.sum(Media.total_watch_time).label("total_watch_time")
        media_count = func.count(Media.id).label("media_count")

        agg_columns = {
            "avg_score": avg_score,
            "avg_scored_by": avg_scored_by,
            "total_episodes": total_episodes,
            "total_watch_time": total_watch_time,
            "media_count": media_count,
        }

        stmt = select(Anime.id)
        stmt = stmt.join(Media, Media.anime_id == Anime.id)

        # Vector search joins
        query_embedding = None
        if query:
            query_embedding = await generate_embedding(query)
            if search_type == SearchType.TITLE:
                stmt = stmt.join(AnimeSearch, AnimeSearch.anime_id == Anime.id)
            elif search_type == SearchType.DESCRIPTION:
                # LEFT JOIN so anime with some media missing embeddings still appear;
                # avg() naturally ignores NULLs from the outer join
                stmt = stmt.outerjoin(MediaSearch, MediaSearch.media_id == Media.id)

        # Pre-aggregation WHERE filters (any-match semantics)
        stmt = apply_anime_pre_filters(stmt, filters)

        # GROUP BY — include AnimeSearch.title_embedding for title search
        # since it's one-to-one with Anime and used in ORDER BY
        group_cols = [Anime.id]
        if query and search_type == SearchType.TITLE:
            group_cols.append(AnimeSearch.title_embedding)
        stmt = stmt.group_by(*group_cols)

        # Post-aggregation HAVING filters (majority/range semantics)
        stmt = apply_anime_having_filters(stmt, filters, agg_columns)

        # Ordering
        if query and query_embedding is not None:
            if search_type == SearchType.TITLE:
                stmt = apply_vector_ordering(
                    stmt, search_type, query_embedding,
                    query=query,
                    title_columns=[Anime.title, Anime.name_eng],
                    extra_columns={SearchType.TITLE: AnimeSearch.title_embedding},
                )
            elif search_type == SearchType.DESCRIPTION:
                avg_distance = func.avg(
                    func.cosine_distance(MediaSearch.description_embedding, cast(query_embedding, Vector))
                ).label("avg_distance")
                stmt = stmt.add_columns(avg_distance)
                stmt = stmt.order_by(avg_distance.asc().nullslast())
        else:
            # Default ordering: weighted score = avg(score) * log10(avg(scored_by) + 1)
            # log10 chosen over ln to dampen the scored_by weight — prevents very popular
            # but mediocre-scored anime from outranking higher-scored niche anime
            weighted = avg_score * func.log(avg_scored_by + 1)
            stmt = stmt.order_by(weighted.desc().nullslast())

        stmt = stmt.limit(limit)

        result = await db.execute(stmt)
        agg_rows = result.all()

        if not agg_rows:
            return []

        # --- Phase B: Detail fetch for matched anime ---
        anime_ids = [row[0] for row in agg_rows]
        detail_stmt = (
            select(Anime)
            .where(Anime.id.in_(anime_ids))
            .options(*self._anime_eager_options())
        )
        detail_result = await db.execute(detail_stmt)
        anime_map = {a.id: a for a in detail_result.scalars().all()}

        # Preserve aggregation query ordering
        return [anime_map[aid] for aid in anime_ids if aid in anime_map]
