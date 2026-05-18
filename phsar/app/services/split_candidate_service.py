"""Admin operations on split candidates: list, dismiss, execute_split.

Execute creates one new Anime row per cluster in the candidate's
payload, re-parents the cluster's Media rows to the new anime, and
re-runs reclassify on both the source (now lighter) and each new
anime. Spoiler cache + merge detection re-run at the end so the new
rows are immediately visible and any post-split duplicates surface.

Sibling to merge_candidate_service. The two share the
reclassify-after-mutation + detect-after-mutation discipline; only the
shape of "what was mutated" differs (re-parent N media into K new
anime here, re-parent M media into 1 surviving anime there).

Rating safety: split execution does NOT touch Ratings.media_id —
ratings remain on the same Media rows whose UUIDs are stable. After
split, a rating on Vigilante S1 still points to that exact media
row; the media has just moved to a different anime parent.
"""

import logging
from uuid import UUID

from sqlalchemy import select, update
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from app.daos.merge_candidate_dao import MergeCandidateDAO
from app.daos.split_candidate_dao import SplitCandidateDAO
from app.exceptions import (
    SplitCandidateAlreadyResolvedError,
    SplitCandidateNotFoundError,
    SplitCandidateStaleError,
)
from app.models.anime import Anime
from app.models.anime_freshness import AnimeFreshness
from app.models.media import Media, RelationType
from app.models.split_candidate import SplitCandidate, SplitCandidateStatus
from app.schemas.admin_schema import (
    SplitCandidateListItem,
    SplitClusterMember,
    SplitClusterPreview,
)
from app.seeders.split_candidate_backfiller import (
    detect_split_candidates_for_anime,
)
from app.services.anime_relation_service import reclassify_anime
from app.services.anime_search_service import anime_title_texts
from app.services.anime_service import strip_season_suffix
from app.services.anime_summary import summarize_anime
from app.services.merge_detection_service import detect_merge_candidates
from app.services.relation_classifier import (
    classify_anime_relations,
    media_to_classifier_node,
)
from app.services.spoiler_service import refresh_spoiler_cache_for_all_users
from app.services.vector_embedding_service import create_anime_embedding

logger = logging.getLogger(__name__)

split_candidate_dao = SplitCandidateDAO()
merge_candidate_dao = MergeCandidateDAO()


async def list_pending(db: AsyncSession) -> list[SplitCandidateListItem]:
    rows = await split_candidate_dao.list_pending_with_anime(db)
    if not rows:
        return []

    anime_ids = {row.anime_id for row in rows}
    # Reuse merge DAO's rating-count helper — same query for the same
    # column. No need for a duplicate.
    rating_counts = await merge_candidate_dao.get_rating_counts_for_anime(db, anime_ids)

    items: list[SplitCandidateListItem] = []
    for row in rows:
        source_anime = row.anime
        media_by_mal = {m.mal_id: m for m in source_anime.media}
        clusters = []
        for cluster in row.clusters:
            members = []
            for mid in cluster["member_mal_ids"]:
                m = media_by_mal.get(mid)
                if m is None:
                    # Classifier saw a member that's no longer under
                    # this anime — likely a merge or manual re-parent
                    # happened post-detection. Skip; admin re-runs
                    # detection to refresh the candidate payload.
                    continue
                members.append(SplitClusterMember(
                    media_uuid=str(m.uuid),
                    mal_id=m.mal_id,
                    title=m.title,
                    media_type=m.media_type.value,
                    relation_type=m.relation_type.value,
                ))
            clusters.append(SplitClusterPreview(
                suggested_anchor_mal_id=cluster["suggested_anchor_mal_id"],
                members=members,
                substance_member_mal_ids=cluster["substance_member_mal_ids"],
                bridge_edges=[tuple(e) for e in cluster.get("bridge_edges", [])],
            ))
        items.append(SplitCandidateListItem(
            uuid=str(row.uuid),
            detected_by=row.detected_by,
            created_at=row.created_at,
            source_anime=summarize_anime(
                source_anime, rating_counts.get(row.anime_id, 0),
            ),
            clusters=clusters,
        ))
    return items


async def _ensure_pending(db: AsyncSession, uuid: UUID) -> SplitCandidate:
    candidate = await split_candidate_dao.get_by_uuid(db, uuid)
    if candidate is None:
        raise SplitCandidateNotFoundError(str(uuid))
    if candidate.status != SplitCandidateStatus.pending:
        raise SplitCandidateAlreadyResolvedError(candidate.status.value)
    return candidate


async def dismiss(db: AsyncSession, uuid: UUID) -> None:
    """Mark as reviewed-but-not-split. No DB mutation otherwise."""
    candidate = await _ensure_pending(db, uuid)
    candidate.status = SplitCandidateStatus.dismissed
    await db.commit()


def _new_anime_from_anchor(anchor_media: Media) -> Anime:
    """Build a fresh Anime row using the anchor media's umbrella fields.
    Mirrors `anime_service.create_anime_from_media`'s strip-season-suffix
    logic + `anime_relation_service.reclassify_anime`'s umbrella copy so
    the new anime row reads identically to one scraped fresh from this
    anchor. Caller adds to session + flushes for the id."""
    return Anime(
        mal_id=anchor_media.mal_id,
        title=strip_season_suffix(anchor_media.title) or anchor_media.title,
        name_eng=strip_season_suffix(anchor_media.name_eng),
        name_jap=strip_season_suffix(anchor_media.name_jap, japanese=True),
        other_names=list(anchor_media.other_names or []),
        description=anchor_media.description,
        cover_image=anchor_media.cover_image,
    )


async def execute_split(db: AsyncSession, uuid: UUID) -> tuple[str, list[str]]:
    """Execute the split: create one new Anime per cluster, re-parent
    the cluster's Media rows, reclassify both sides, then re-run merge
    detection and refresh the spoiler cache.

    Returns `(source_anime_uuid, [new_anime_uuid, ...])`. The source
    anime's UUID is unchanged — its umbrella may reclassify if the
    smaller media set picks a different anchor, but the row identity
    persists. Ratings on the moved Media rows stay attached (Media UUIDs
    are stable across re-parenting).

    Fail-loud on stale candidate: if the classifier on the cluster
    subset picks a different anchor than the candidate's
    suggested_anchor_mal_id, MAL data has shifted between detection and
    execution — raise SplitCandidateStaleError so admin re-runs
    detection.
    """
    candidate = await _ensure_pending(db, uuid)

    source_anime = (await db.execute(
        select(Anime).where(Anime.id == candidate.anime_id)
        .options(selectinload(Anime.media).selectinload(Media.relation_edges))
    )).scalars().first()
    if source_anime is None:
        # FK cascade should've killed the candidate when the anime
        # disappeared; treat as not-found if it didn't.
        raise SplitCandidateNotFoundError(str(uuid))

    media_by_mal = {m.mal_id: m for m in source_anime.media}
    new_anime_uuids: list[str] = []
    new_anime_ids: list[int] = []

    for cluster in candidate.clusters:
        cluster_mal_ids = set(cluster["member_mal_ids"])
        cluster_media = [
            media_by_mal[mid] for mid in cluster["member_mal_ids"]
            if mid in media_by_mal
        ]
        if not cluster_media:
            # Cluster fully evaporated since detection (merge, manual
            # cleanup). Skip — admin re-runs detection if anything else
            # matters.
            continue

        # Run the classifier on the cluster subset to verify the anchor
        # still matches. If MAL data has shifted between detection and
        # execution (sweep added/removed a sequel), the classifier may
        # pick a different anchor — fail-loud so admin re-detects.
        sub_nodes = {m.mal_id: media_to_classifier_node(m) for m in cluster_media}
        sub_edges = [
            (m.mal_id, target, rel)
            for m in cluster_media
            if m.relation_edges is not None
            for target, rel in m.relation_edges.edges
            if target in cluster_mal_ids
        ]
        sub_classifications, sub_anchor = classify_anime_relations(sub_nodes, sub_edges)
        expected = cluster["suggested_anchor_mal_id"]
        if sub_anchor != expected:
            raise SplitCandidateStaleError(expected, sub_anchor)

        anchor_media = next(m for m in cluster_media if m.mal_id == sub_anchor)
        new_anime = _new_anime_from_anchor(anchor_media)
        db.add(new_anime)
        await db.flush()  # need new_anime.id for re-parent + freshness
        new_anime.freshness = AnimeFreshness(
            last_checked_at=None, stable_check_count=0,
        )
        new_anime_uuids.append(str(new_anime.uuid))
        new_anime_ids.append(new_anime.id)

        # Re-parent cluster media. UPDATE in one shot — bulk is cheaper
        # than per-row and the cascading sidecar tables don't care.
        cluster_media_ids = [m.id for m in cluster_media]
        await db.execute(
            update(Media)
            .where(Media.id.in_(cluster_media_ids))
            .values(anime_id=new_anime.id)
        )

        # Stamp classifier-derived relation_types on each cluster media.
        # The classifier saw a subset graph so labels may differ from
        # the pre-split state (e.g., an in-cluster main → side_story
        # demotion via substance gate).
        for m in cluster_media:
            new_rt = sub_classifications[m.mal_id]
            m.relation_type = RelationType(new_rt)

        await create_anime_embedding(
            db,
            anime_id=new_anime.id,
            title_texts=anime_title_texts(new_anime),
            description_text=new_anime.description or "",
        )

        logger.info(
            "Split: created anime id=%d %r from cluster of %d media "
            "(parent was anime id=%d %r)",
            new_anime.id, new_anime.title, len(cluster_media),
            source_anime.id, source_anime.title,
        )

    await db.flush()

    # Expire the cached `.media` collection on the source so the re-load
    # below sees the now-smaller set. The bulk UPDATE bypasses ORM
    # relationship tracking; without this, the identity map serves the
    # pre-split collection and reclassify operates on stale data.
    db.expire(source_anime, ["media"])

    # Re-load source with its now-smaller media set, then reclassify so
    # the umbrella reflects any anchor shift. The previous anchor may
    # have been valid for the contaminated set but no longer fits with
    # the orphan clusters extracted.
    source_anime = (await db.execute(
        select(Anime).where(Anime.id == source_anime.id)
        .options(selectinload(Anime.media).selectinload(Media.relation_edges))
    )).scalars().first()
    if source_anime is not None and source_anime.media:
        await reclassify_anime(db, source_anime)

    # Detect post-split: nested splits on each new anime (rare — would
    # require the cluster itself to contain disjoint chains) plus the
    # source in case the reclassify pulled together a previously-not-
    # flagged shape. Source is already loaded with sidecars from the
    # post-expire re-fetch above.
    if source_anime is not None:
        await detect_split_candidates_for_anime(
            db, source_anime, detected_by="post_split_source",
        )
    for new_id in new_anime_ids:
        new_anime = (await db.execute(
            select(Anime).where(Anime.id == new_id)
            .options(selectinload(Anime.media).selectinload(Media.relation_edges))
        )).scalars().first()
        if new_anime is not None:
            await detect_split_candidates_for_anime(
                db, new_anime, detected_by="post_split_new",
            )

    # Mark the candidate resolved before merge detection runs so its
    # cascade doesn't interact with the merge_candidate inserts.
    candidate.status = SplitCandidateStatus.split

    # A freshly-split-out anime may match an existing row (e.g. the user
    # pre-scraped Vigilante separately before BNHA was re-scraped and
    # re-pulled Vigilante in).
    if new_anime_ids:
        await detect_merge_candidates(db, new_anime_ids=new_anime_ids)

    await db.commit()

    # Spoiler cache stores media ids, not anime ids, but the frontier
    # algorithm runs per-anime. Recompute globally because anime
    # boundaries shifted.
    await refresh_spoiler_cache_for_all_users(db)

    return str(source_anime.uuid) if source_anime else "", new_anime_uuids
