import logging
from typing import Any, NamedTuple
from uuid import UUID

from pgvector.sqlalchemy import Vector
from sqlalchemy import and_, case, cast, func, or_, select, text
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import aliased, selectinload

from app.daos.base_mal_id_dao import MalIdDAO
from app.daos.search_filters import (
    apply_anime_having_filters,
    apply_anime_pre_filters,
    apply_vector_ordering,
    weighted_mean_score_expr,
    weighted_mean_votes_expr,
    weighted_score_expr,
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
# back to the long-tail safety nets (tier 4, or tier 5 once aged out).
SWEEP_RECENT_MAIN_YEARS = 5

# Long-tail border (v0.14.8). Media not airing / stabilizing / recent-main are
# refreshed only on this safety net. Shared by the media-level selection atoms
# AND the (now count-only) anime atoms so there is exactly one source of truth.
SWEEP_LONG_TAIL_DAYS = 90

# Tier 5: media whose premiere is this far in the past have effectively frozen MAL
# metadata, so they sit on a slower net than the 90-day long tail. The long cycle
# is the TERMINAL bucket — every media drains into it once it stops airing and ages
# past the recent-main window, and nothing ever leaves — so it is the only tier
# whose nightly draw grows without bound as the catalog does. Halving the cadence
# for the aged cohort is what keeps that draw flat.
#
# Implemented as a per-row WINDOW on the single long-tail atom rather than as a
# fifth OR-branch: a separate branch would need tier 4 narrowed by `not_(archival)`
# to not shadow it, and that coupling is the kind you forget. See `_media_sweep_atoms`.
SWEEP_ARCHIVAL_AGE_YEARS = 10
SWEEP_ARCHIVAL_DAYS = 180

# Tier 2: burn the initial stability sampling for the first N sweeps of a
# row's life. One threshold shared by the media selection atoms, the anime
# count-card atoms, and the probe gate so media and anime stay consistent.
SWEEP_STABILIZE_THRESHOLD = 3


class _SweepAtoms(NamedTuple):
    """Anime-level cycle-membership atoms for the admin Overview count card
    (`count_by_sweep_tier_priority`). Pure roll-ups of the anime's MEDIA tiers,
    so the anime breakdown stays consistent with the media breakdown — an anime
    inherits its most-urgent media's tier under the priority cascade.

    All three read columns off `_anime_sweep_cte`, which rolls the media up in
    one pass; the stabilizing tier reads that CTE's `min_stable` directly and so
    isn't an atom here.
    """
    airing_now: Any
    recent_main: Any
    archival: Any


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
    archival: Any
    due_weekly: Any
    due_long_tail: Any


def _media_sweep_atoms(mf_alias) -> _MediaSweepAtoms:
    """Build the media-level sweep-tier atoms against the given
    MediaFreshness alias."""
    last_checked = func.coalesce(mf_alias.last_checked_at, Media.created_at)
    stable = func.coalesce(mf_alias.stable_check_count, 0)
    now = func.now()
    week_ago = now - text("interval '7 days'")
    recent_main_cutoff = now - text(f"interval '{SWEEP_RECENT_MAIN_YEARS} years'")
    archival_cutoff = now - text(f"interval '{SWEEP_ARCHIVAL_AGE_YEARS} years'")
    archival = Media.aired_from < archival_cutoff

    return _MediaSweepAtoms(
        airing_now=Media.airing_status == AIRING_STATUS_CURRENTLY_AIRING,
        still_stabilizing=stable < SWEEP_STABILIZE_THRESHOLD,
        recent_main=and_(
            Media.relation_type == RelationType.Main,
            Media.aired_from >= recent_main_cutoff,
        ),
        archival=archival,
        due_weekly=last_checked < week_ago,
        # ONE long-tail atom with a per-row window, rather than two mutually-
        # exclusive due-branches: each media is compared against the cutoff its own
        # cohort uses. That keeps the tiers independent predicates (a `not_(archival)`
        # narrowing on tier 4 would have to be kept in sync by hand, and forgetting
        # it makes the archival branch dead code), and it makes the NULL case fall
        # out for free — an undated media fails the WHEN and lands on the 90-day
        # ELSE, which is exactly what it should get.
        due_long_tail=last_checked < now - case(
            (archival, text(f"interval '{SWEEP_ARCHIVAL_DAYS} days'")),
            else_=text(f"interval '{SWEEP_LONG_TAIL_DAYS} days'"),
        ),
    )


def _anime_sweep_cte():
    """Every per-anime input the tier cascade needs, rolled up from media in ONE
    pass grouped by `media.anime_id`.

    It has to be one pre-aggregated pass rather than correlated subqueries per
    atom. `_tier_bucket` emits one `WHEN` per stabilize level, so a correlated
    `min_stable` appears in the compiled SQL once per level and Postgres plans
    that many independent SubPlans with no cross-node caching — each re-scanning
    that anime's media. The cost grows faster than the catalogue does, on a card
    that loads with every admin Overview.

    LEFT JOIN this to `Anime` and **do not coalesce the result**: a media-less
    anime gets no CTE row, so every atom reads NULL, every `WHEN` in the cascade
    is not-true, and it falls through to the `else_` (`long_cycle`) — which is
    what it should get. Coalescing `min_stable` to 0 would bucket it as
    `stabilizing_0` instead. The `coalesce` INSIDE the CTE is the different case
    of a media that simply has no freshness sidecar yet.
    """
    mf = aliased(MediaFreshness)
    now = func.now()
    recent_main_cutoff = now - text(f"interval '{SWEEP_RECENT_MAIN_YEARS} years'")
    return (
        select(
            Media.anime_id.label("anime_id"),
            func.bool_or(
                Media.airing_status == AIRING_STATUS_CURRENTLY_AIRING
            ).label("airing_now"),
            func.bool_or(
                and_(
                    Media.relation_type == RelationType.Main,
                    Media.aired_from >= recent_main_cutoff,
                )
            ).label("recent_main"),
            # MAX, not an EXISTS pair — see `_sweep_atoms`' archival note.
            func.max(Media.aired_from).label("newest_aired"),
            # The anime's least-settled member. While the anime is in the
            # stabilizing tier this is < threshold, so it maps onto exactly one
            # `stabilizing_<n>` bucket.
            func.min(func.coalesce(mf.stable_check_count, 0)).label("min_stable"),
        )
        .outerjoin(mf, mf.media_id == Media.id)
        .group_by(Media.anime_id)
        .cte("anime_sweep_facts")
    )


def _sweep_atoms(cte) -> _SweepAtoms:
    """Project `_anime_sweep_cte`'s rolled-up columns into the membership atoms
    `_tier_bucket` consumes."""
    archival_cutoff = func.now() - text(f"interval '{SWEEP_ARCHIVAL_AGE_YEARS} years'")
    # "The newest thing this franchise aired is older than the cutoff" — the ∀
    # quantifier, where airing_now / recent_main are ∃. That's the same documented
    # rule ("an anime inherits its most-urgent media's tier"), not a special case:
    # those two are the FAST end of the cascade so any qualifying member wins,
    # while archival is the SLOW end so every member must qualify. A future editor
    # "fixing" this into a bool_or for symmetry would be wrong.
    #
    # MAX also drops the NULL hazard for free: it ignores NULLs, so an all-undated
    # anime yields `NULL < cutoff` → not true → long_cycle.
    return _SweepAtoms(
        airing_now=cte.c.airing_now,
        recent_main=cte.c.recent_main,
        archival=cte.c.newest_aired < archival_cutoff,
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
        """Fetch anime by UUID with all media eagerly loaded (including genres/studios per media)
        plus the completion sidecar (story-complete flag for the detail page)."""
        stmt = (
            select(Anime)
            .filter(Anime.uuid == uuid)
            .options(*self._anime_eager_options(), selectinload(Anime.completion))
        )
        result = await db.execute(stmt)
        return result.scalars().first()

    async def score_top_percent(self, db: AsyncSession, anime_id: int) -> int | None:
        """Where this anime ranks among all scored anime by its
        confidence-weighted MAL score, as a rank-based "top N%" (lower = better,
        worst-scored anime = 100).

        Per-anime metric is `S_w * log10(V_w + 1)` where `S_w`/`V_w` are the
        relation-weighted means (`RELATION_SCORE_WEIGHTS` — Main + AlternativeVersion
        only) the detail card shows as `avg_score` / `avg_scored_by`, so the rank
        lines up with the displayed pill and both move together (higher in both →
        higher rank). Returns None when the anime has no scored Main/Alt media or
        the catalog has none scored."""
        mean_score = weighted_mean_score_expr()
        per_anime = (
            select(
                Media.anime_id.label("anime_id"),
                weighted_score_expr(mean_score, weighted_mean_votes_expr()).label("metric"),
            )
            .group_by(Media.anime_id)
            .having(mean_score.is_not(None))
            .cte("per_anime_score")
        )
        # Single pass over the per-anime metric set: rank() (ties share the lowest
        # rank) minus 1 is the count of strictly-better anime, count() over the
        # whole window is the scored total. Avoids referencing the CTE twice (a
        # scalar subquery + a filtered count both scanned it before).
        ranked = (
            select(
                per_anime.c.anime_id.label("anime_id"),
                (func.rank().over(order_by=per_anime.c.metric.desc()) - 1).label("better"),
                func.count().over().label("total"),
            )
            .select_from(per_anime)
            .subquery()
        )
        row = (
            await db.execute(
                select(ranked.c.better, ranked.c.total).where(ranked.c.anime_id == anime_id)
            )
        ).one_or_none()
        # No row → this anime has no scored media (filtered out by HAVING).
        if row is None or row.total == 0:
            return None
        # Rank-based top N% (see MediaDAO.score_top_percent): ceil(rank/total*100).
        return ((row.better + 1) * 100 + row.total - 1) // row.total

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
          2. stable_check_count < 3 — burn the initial stability sampling.
          3. Last checked > 7 days ago AND this media is a recent main
             (relation_type=main, aired_from within SWEEP_RECENT_MAIN_YEARS).
          4. Last checked longer ago than this media's own long-tail window —
             SWEEP_LONG_TAIL_DAYS (90), or SWEEP_ARCHIVAL_DAYS (180) once it
             premiered over SWEEP_ARCHIVAL_AGE_YEARS ago and its MAL metadata has
             effectively frozen. One predicate, per-row window.

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
            # anime-level cascade but per media. Tier 3 is the weekly cycle gated by
            # 7-day staleness; `due_long_tail` is the safety net, whose window is
            # 90 or 180 days depending on the media's own premiere age (see the atom).
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
        "archival_cycle",
    )

    @classmethod
    def _tier_bucket(cls, atoms, stable_expr) -> Any:
        """The shared priority-cascade label (airing_now > stabilizing >
        weekly_cycle > archival_cycle > long_cycle) for either grain's atoms —
        single source of truth so the anime + media count cards can't drift.

        `archival_cycle` must be an explicit branch BEFORE the `else_`, since
        `long_cycle` IS the else_ and an appended branch would never fire. It sits
        after `recent_main` so a franchise with a recent main season still reads as
        weekly even when it also has decade-old members.

        The stabilizing tier is split into per-check sub-labels
        `stabilizing_<n>` (n = 0..SWEEP_STABILIZE_THRESHOLD-1) so the card can
        show the stabilization pipeline. `stable_expr` is the grain's
        stabilization counter: the media's own `stable_check_count` for the
        media grain, the MIN across an anime's media (its least-settled
        member) for the anime grain. `_count_by_tier` folds the sub-labels
        back into the `stabilizing` total + a per-check breakdown. Dynamic in
        the threshold — retuning SWEEP_STABILIZE_THRESHOLD reshapes the
        buckets with no other change.

        `stable_expr == n` for n < threshold IS the stabilizing condition (a
        graduated row sits at stable >= threshold and matches no sub-label),
        so no separate `still_stabilizing` guard is needed — and airing_now
        comes first in the cascade, so an airing-but-unstable row still lands
        under airing_now."""
        stabilizing_cases = [
            (stable_expr == n, f"stabilizing_{n}")
            for n in range(SWEEP_STABILIZE_THRESHOLD)
        ]
        return case(
            (atoms.airing_now, "airing_now"),
            *stabilizing_cases,
            (atoms.recent_main, "weekly_cycle"),
            (atoms.archival, "archival_cycle"),
            else_="long_cycle",
        ).label("bucket")

    async def _count_by_tier(self, db: AsyncSession, stmt) -> dict[str, Any]:
        """Run a `(bucket, count)` GROUP BY statement and fold it into a
        zero-filled result: the 5 cycle-membership totals plus
        `stabilizing_by_check`, a {check_count: count} breakdown of the
        stabilizing bucket. The CASE emits `stabilizing_<n>` sub-labels which
        sum back into the `stabilizing` total, so absent buckets read 0.

        Contract: `stabilizing_by_check` ALWAYS carries exactly
        SWEEP_STABILIZE_THRESHOLD keys (0..threshold-1, zero-filled) — the
        SweepTiersCard derives the pipeline depth from the key count, so keep
        the breakdown dense even when a check bucket is empty."""
        counts: dict[str, Any] = dict.fromkeys(self._TIER_BUCKETS, 0)
        by_check = dict.fromkeys(range(SWEEP_STABILIZE_THRESHOLD), 0)
        for bucket_name, count in (await db.execute(stmt)).all():
            if bucket_name.startswith("stabilizing_"):
                by_check[int(bucket_name.removeprefix("stabilizing_"))] = count
                counts["stabilizing"] += count
            else:
                counts[bucket_name] = count
        counts["stabilizing_by_check"] = by_check
        return counts

    async def count_by_sweep_tier_priority(
        self, db: AsyncSession,
    ) -> dict[str, Any]:
        """5 mutually-exclusive cycle-MEMBERSHIP bucket counts in priority
        cascade: airing_now > stabilizing > weekly_cycle > archival_cycle >
        long_cycle.
        Sum equals total anime count. Powers the admin Overview
        tier-breakdown card.

        Membership atoms are roll-ups of the anime's MEDIA tiers (see
        `_SweepAtoms`), so this stays consistent with
        `count_media_by_sweep_tier_priority` — an anime inherits its
        most-urgent media's tier. `weekly_cycle` = has a recent main (no
        airing/stabilizing media); `long_cycle` = the else. The stabilizing
        total is further broken down per check count (see `_tier_bucket`).

        OUTER join to the facts CTE, un-coalesced, so a media-less anime falls
        through the whole cascade to `long_cycle` — see `_anime_sweep_cte`.
        """
        facts = _anime_sweep_cte()
        bucket = self._tier_bucket(_sweep_atoms(facts), facts.c.min_stable)
        stmt = (
            select(bucket, func.count(Anime.id))
            .select_from(Anime)
            .outerjoin(facts, facts.c.anime_id == Anime.id)
            .group_by(bucket)
        )
        return await self._count_by_tier(db, stmt)

    async def count_media_by_sweep_tier_priority(
        self, db: AsyncSession,
    ) -> dict[str, Any]:
        """Media-level analogue of `count_by_sweep_tier_priority` (v0.14.8):
        5 mutually-exclusive cycle-MEMBERSHIP bucket counts in the same
        priority cascade, but per media. Sum equals total media count.
        Powers the media side of the admin Overview tier-breakdown toggle.

        Membership-only, same rationale as the anime version — the staleness
        atoms are excluded so a bucket doesn't empty itself when a sweep
        refreshes its members. `stabilizing` here is the media
        stable_check_count < SWEEP_STABILIZE_THRESHOLD bucket; `long_cycle`
        is the else (stable + not airing + not a
        recent main), refreshed only on the 90-day net. The stabilizing total
        is further broken down per check count (see `_tier_bucket`).
        """
        mf = aliased(MediaFreshness)
        stable = func.coalesce(mf.stable_check_count, 0)
        bucket = self._tier_bucket(_media_sweep_atoms(mf), stable)
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
        # Score/votes are the relation-weighted means over Main+Alt media
        # (RELATION_SCORE_WEIGHTS) — this scopes the default ordering AND the
        # score/scored_by HAVING filters (via agg_columns) so they match the
        # displayed avg (anime_search_service._compute_anime_aggregates). Episode
        # /watch-time/genre-majority aggregates stay over ALL media.
        avg_score = weighted_mean_score_expr().label("avg_score")
        avg_scored_by = weighted_mean_votes_expr().label("avg_scored_by")
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

        # GROUP BY the PK alone. Title search orders on the anime_search
        # embedding, which lives on another table, so it can't ride functional
        # dependency the way Anime's own columns do — it's aggregated in the
        # ORDER BY instead (`aggregate_distance` below). Grouping by the vector
        # would put 384 floats in the hash/sort key of every input row.
        stmt = stmt.group_by(Anime.id)

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
                    # AnimeSearch is 1:1 with Anime, so MIN over the group is
                    # that row's own distance — the aggregate exists to satisfy
                    # the GROUP BY, not to pick between candidates.
                    aggregate_distance=True,
                )
            elif search_type == SearchType.DESCRIPTION:
                avg_distance = func.avg(
                    func.cosine_distance(MediaSearch.description_embedding, cast(query_embedding, Vector))
                ).label("avg_distance")
                stmt = stmt.add_columns(avg_distance)
                stmt = stmt.order_by(avg_distance.asc().nullslast())
        else:
            # Default ordering: weighted score = S_w * log10(V_w + 1) over Main+Alt
            weighted = weighted_score_expr(avg_score, avg_scored_by)
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
            .options(*self._anime_eager_options(), selectinload(Anime.completion))
        )
        detail_result = await db.execute(detail_stmt)
        anime_map = {a.id: a for a in detail_result.scalars().all()}

        # Preserve aggregation query ordering
        return [anime_map[aid] for aid in anime_ids if aid in anime_map]
