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
from app.models.anime_search import AnimeSearch
from app.models.media import Media, RelationType
from app.models.media_freshness import MediaFreshness
from app.models.media_genre import MediaGenre
from app.models.media_search import MediaSearch
from app.models.media_studio import MediaStudio
from app.schemas.media_filter_schema import MediaSearchFilters, SearchType
from app.services.relation_classifier import AIRING_STATUS_CURRENTLY_AIRING
from app.services.vector_embedding_service import generate_embedding

logger = logging.getLogger(__name__)

# Tier 3 of the nightly sweep: only weekly-probe franchises whose latest
# main media aired within this window. Older main-only franchises fall
# back to tier 4 (the long-tail safety net).
SWEEP_RECENT_MAIN_YEARS = 5

# Single long-tail border (v0.14.8). Media not airing / stabilizing /
# recent-main are refreshed only on this safety net. Shared by the
# media-level selection atoms AND the (now count-only) anime atoms so
# there is exactly one source of truth — no 180-vs-90 drift.
SWEEP_LONG_TAIL_DAYS = 90

# Tier 2: burn the initial stability sampling for the first N sweeps of a
# row's life. One threshold shared by the media selection atoms, the anime
# count-card atoms, and the probe gate so media and anime stay consistent.
SWEEP_STABILIZE_THRESHOLD = 5


class _SweepAtoms(NamedTuple):
    """Anime-level cycle-membership atoms for the admin Overview count card
    (`count_by_sweep_tier_priority`). As of v0.14.8 these are pure roll-ups
    of the anime's MEDIA tiers — every atom is an EXISTS over the anime's
    media — so the anime breakdown stays consistent with the media breakdown
    (an anime inherits its most-urgent media's tier under the priority
    cascade). Crucially `still_stabilizing` reads the per-media
    `MediaFreshness.stable_check_count`, NOT the anime probe counter on
    `AnimeFreshness`: refresh selection is media-level, so the card must
    reflect media state, not the probe clock. Refresh selection itself lives
    in `_media_sweep_atoms`; this is just a coarser lens on the same cycle.
    """
    airing_now: Any
    still_stabilizing: Any
    recent_main: Any


class _MediaSweepAtoms(NamedTuple):
    """Media-level analogue of `_SweepAtoms` (v0.14.8). The same four-tier
    cascade, but every atom is a DIRECT predicate on the media row + its
    `MediaFreshness` sidecar rather than a correlated EXISTS against an
    anime's children. This is the whole point of the media-level
    conversion: a still-airing umbrella's stable side-stories each evaluate
    `airing_now=False`, `recent_main=False`, `still_stabilizing=False`
    individually, so only the genuinely-due media surface — One Piece no
    longer drags its 68 finished members through a refresh every night.

    Consumers mirror the anime split: `select_due_media_for_sweep` wants
    DUE (membership AND staleness); `count_media_by_sweep_tier_priority`
    wants membership ONLY.
    """
    airing_now: Any
    still_stabilizing: Any
    recent_main: Any
    due_weekly: Any
    due_long_tail: Any


def _media_sweep_atoms(mf_alias) -> _MediaSweepAtoms:
    """Build the media-level sweep-tier atoms against the given
    MediaFreshness alias."""
    last_checked = func.coalesce(mf_alias.last_checked_at, Media.created_at)
    stable = func.coalesce(mf_alias.stable_check_count, 0)
    now = func.now()
    week_ago = now - text("interval '7 days'")
    long_tail_ago = now - text(f"interval '{SWEEP_LONG_TAIL_DAYS} days'")
    recent_main_cutoff = now - text(f"interval '{SWEEP_RECENT_MAIN_YEARS} years'")

    return _MediaSweepAtoms(
        airing_now=Media.airing_status == AIRING_STATUS_CURRENTLY_AIRING,
        still_stabilizing=stable < SWEEP_STABILIZE_THRESHOLD,
        recent_main=and_(
            Media.relation_type == RelationType.Main,
            Media.aired_from >= recent_main_cutoff,
        ),
        due_weekly=last_checked < week_ago,
        due_long_tail=last_checked < long_tail_ago,
    )


def _sweep_atoms() -> _SweepAtoms:
    """Build the anime membership atoms as roll-ups of the anime's MEDIA
    tiers (EXISTS over media). `still_stabilizing` reads the per-media
    `MediaFreshness.stable_check_count` so it matches the media card — using
    the anime probe counter here let an anime show as weekly/stable while all
    its media were still media-stabilizing (the v0.14.8 inconsistency)."""
    recent_main_cutoff = func.now() - text(f"interval '{SWEEP_RECENT_MAIN_YEARS} years'")
    mf = aliased(MediaFreshness)

    airing_now = exists().where(
        and_(
            Media.anime_id == Anime.id,
            Media.airing_status == AIRING_STATUS_CURRENTLY_AIRING,
        )
    )
    still_stabilizing = (
        select(1)
        .select_from(Media)
        .outerjoin(mf, mf.media_id == Media.id)
        .where(
            and_(
                Media.anime_id == Anime.id,
                func.coalesce(mf.stable_check_count, 0) < SWEEP_STABILIZE_THRESHOLD,
            )
        )
        .exists()
    )
    recent_main = exists().where(
        and_(
            Media.anime_id == Anime.id,
            Media.relation_type == RelationType.Main,
            Media.aired_from >= recent_main_cutoff,
        )
    )
    return _SweepAtoms(
        airing_now=airing_now,
        still_stabilizing=still_stabilizing,
        recent_main=recent_main,
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

    async def select_due_media_for_sweep(
        self, db: AsyncSession, limit: int,
    ) -> list[Media]:
        """Media due for the nightly update sweep, oldest-first (v0.14.8).

        Selection is media-grained: the LIMIT bounds the number of
        /anime/{id}/full calls (the true 1-req/s MAL cost unit), and a
        still-airing umbrella's stable members are skipped instead of
        re-refreshed every night. Four tiers OR'd together, every atom a
        direct predicate on the media row + its MediaFreshness sidecar:
          1. This media is "Currently Airing" — always due.
          2. stable_check_count < 5 — burn the initial stability sampling.
          3. Last checked > 7 days ago AND this media is a recent main
             (relation_type=main, aired_from within SWEEP_RECENT_MAIN_YEARS).
          4. Last checked > SWEEP_LONG_TAIL_DAYS (90) ago — long-tail net.

        Eager-loads the parent Anime AND its FULL media set (+ anime
        freshness) because `reclassify_anime(anime)` and the relations
        probe read `anime.media`, and `lazy="raise"` is global. SQLAlchemy's
        identity map collapses the shared Anime instance across all of an
        anime's due-media rows, so the dispatcher can group by `anime.id`
        and get one Anime with one complete `.media` collection.
        """
        mf = aliased(MediaFreshness)
        atoms = _media_sweep_atoms(mf)

        # Nested loads for the parent's full media set — everything the
        # refresh loop, the reclassifier, and the probe touch, so nothing
        # trips lazy="raise". The due-media rows are a subset of that set and
        # resolve to the SAME identity-map instances, so loading these under
        # selectinload(Anime.media) populates them too — no separate top-level
        # child load needed (would double the M2M/edge hydration for the due
        # subset during the post-migration herd).
        media_child_loads = (
            selectinload(Media.freshness),
            selectinload(Media.relation_edges),
            selectinload(Media.media_genre).selectinload(MediaGenre.genre),
            selectinload(Media.media_studio).selectinload(MediaStudio.studio),
        )

        stmt = (
            select(Media)
            .outerjoin(mf, mf.media_id == Media.id)
            # DUE semantics: membership AND staleness, mirroring the old
            # anime-level cascade but per media. Tier 3 is the weekly cycle
            # gated by 7-day staleness; tier 4 the 90-day long-tail net.
            .where(or_(
                atoms.airing_now,
                atoms.still_stabilizing,
                and_(atoms.due_weekly, atoms.recent_main),
                atoms.due_long_tail,
            ))
            # `nullsfirst()` puts never-checked media at the front (a NULL
            # last_checked_at is maximum staleness). created_at / id
            # tiebreaks keep ordering deterministic, not accidental on PK.
            .order_by(
                mf.last_checked_at.asc().nullsfirst(),
                Media.created_at.asc(),
                Media.id.asc(),
            )
            .options(
                selectinload(Media.anime).options(
                    selectinload(Anime.freshness),
                    selectinload(Anime.media).options(*media_child_loads),
                ),
            )
            .limit(limit)
        )
        result = await db.execute(stmt)
        return list(result.scalars().all())

    _TIER_BUCKETS: tuple[str, ...] = (
        "airing_now",
        "stabilizing",
        "weekly_cycle",
        "long_cycle",
    )

    @classmethod
    def _tier_bucket(cls, atoms) -> Any:
        """The shared priority-cascade label (airing_now > stabilizing >
        weekly_cycle > long_cycle) for either grain's atoms — single source
        of truth so the anime + media count cards can't drift."""
        return case(
            (atoms.airing_now, "airing_now"),
            (atoms.still_stabilizing, "stabilizing"),
            (atoms.recent_main, "weekly_cycle"),
            else_="long_cycle",
        ).label("bucket")

    async def _count_by_tier(self, db: AsyncSession, stmt) -> dict[str, int]:
        """Run a `(bucket, count)` GROUP BY statement and fold it into a
        zero-filled bucket dict (so absent buckets read 0, not missing)."""
        counts = {b: 0 for b in self._TIER_BUCKETS}
        for bucket_name, count in (await db.execute(stmt)).all():
            counts[bucket_name] = count
        return counts

    async def count_by_sweep_tier_priority(
        self, db: AsyncSession,
    ) -> dict[str, int]:
        """4 mutually-exclusive cycle-MEMBERSHIP bucket counts in priority
        cascade: airing_now > stabilizing > weekly_cycle > long_cycle.
        Sum equals total anime count. Powers the admin Overview
        tier-breakdown card.

        Membership atoms are roll-ups of the anime's MEDIA tiers (see
        `_SweepAtoms`), so this stays consistent with
        `count_media_by_sweep_tier_priority` — an anime inherits its
        most-urgent media's tier. `weekly_cycle` = has a recent main (no
        airing/stabilizing media); `long_cycle` = the else.
        """
        bucket = self._tier_bucket(_sweep_atoms())
        stmt = select(bucket, func.count(Anime.id)).select_from(Anime).group_by(bucket)
        return await self._count_by_tier(db, stmt)

    async def count_media_by_sweep_tier_priority(
        self, db: AsyncSession,
    ) -> dict[str, int]:
        """Media-level analogue of `count_by_sweep_tier_priority` (v0.14.8):
        4 mutually-exclusive cycle-MEMBERSHIP bucket counts in the same
        priority cascade, but per media. Sum equals total media count.
        Powers the media side of the admin Overview tier-breakdown toggle.

        Membership-only, same rationale as the anime version — the staleness
        atoms are excluded so a bucket doesn't empty itself when a sweep
        refreshes its members. `stabilizing` here is the media 5-check
        threshold; `long_cycle` is the else (stable + not airing + not a
        recent main), refreshed only on the 90-day net.
        """
        mf = aliased(MediaFreshness)
        bucket = self._tier_bucket(_media_sweep_atoms(mf))
        stmt = (
            select(bucket, func.count(Media.id))
            .outerjoin(mf, mf.media_id == Media.id)
            .group_by(bucket)
        )
        return await self._count_by_tier(db, stmt)

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
