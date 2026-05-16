"""Per-anime two-pass classification + umbrella drift fix.

Called from two sites:
- `relation_backfiller` walks the catalog at startup and reclassifies
  every anime via this helper.
- `merge_candidate_service.merge` reclassifies the survivor after
  re-parenting B's media onto A — the consolidated graph may pick a
  different anchor (e.g. B's anchor is older) and reclassify weak
  mains absorbed from B.

`reclassify_anime` assumes `anime.media` is loaded with each media's
`relation_edges` sidecar. Edges pointing outside the anime's own media
set are filtered (cross-links, stale targets); the classifier requires
both endpoints in `nodes`.
"""

from collections.abc import Iterable
from typing import TypedDict

from sqlalchemy.ext.asyncio import AsyncSession

from app.models.anime import Anime
from app.models.media import Media, RelationType
from app.services.anime_service import strip_season_suffix
from app.services.relation_classifier import (
    classify_anime_relations,
    media_to_classifier_node,
    pick_anchor,
)
from app.services.vector_embedding_service import regenerate_anime_embedding


def _build_classifier_graph(
    media: Iterable[Media],
) -> tuple[dict[int, dict], list[tuple[int, int, str]]]:
    """Project a media iterable into (nodes, in-graph-only edges) ready
    for `classify_anime_relations`. Edges pointing outside this media
    set (cross-links, stale targets) are dropped — the classifier
    requires both endpoints in `nodes`.
    """
    media_list = list(media)
    nodes = {m.mal_id: media_to_classifier_node(m) for m in media_list}
    graph_ids = set(nodes.keys())
    edges: list[tuple[int, int, str]] = []
    for m in media_list:
        if m.relation_edges is None:
            continue
        for target_mal_id, rel in m.relation_edges.edges:
            if target_mal_id in graph_ids:
                edges.append((m.mal_id, target_mal_id, rel))
    return nodes, edges


class ReclassifyDiff(TypedDict):
    reclassified: list[tuple[int, str, str]]  # (mal_id, old_rt, new_rt)
    anchor_changed: bool
    # True if any of the 7 umbrella fields differs from the anchor
    # media's current value (anchor_changed implies this).
    umbrella_drifted: bool
    old_anchor_mal_id: int
    new_anchor_mal_id: int


async def reclassify_anime(
    db: AsyncSession, anime: Anime, *, dry_run: bool = False,
) -> ReclassifyDiff | None:
    """Re-classify all media under `anime` and rewrite the umbrella row
    if the canonical anchor or any of the 7 umbrella fields drifted.
    Returns `None` when no changes are needed; otherwise a diff dict.
    Caller commits.
    """
    nodes, edges = _build_classifier_graph(anime.media)
    classifications = classify_anime_relations(nodes, edges)
    new_anchor_mal_id = pick_anchor(nodes)

    current_by_mal = {m.mal_id: m for m in anime.media}
    reclassified: list[tuple[int, str, str]] = []
    for mal_id, new_rt in classifications.items():
        old_rt = current_by_mal[mal_id].relation_type.value
        if old_rt != new_rt:
            reclassified.append((mal_id, old_rt, new_rt))

    # Mirrors create_anime_from_media's field copy + strip so the
    # post-rewrite anime row looks identical to one scraped fresh from
    # this anchor.
    new_anchor_media = current_by_mal[new_anchor_mal_id]
    new_title = strip_season_suffix(new_anchor_media.title) or new_anchor_media.title
    new_name_eng = strip_season_suffix(new_anchor_media.name_eng)
    new_name_jap = strip_season_suffix(new_anchor_media.name_jap, japanese=True)
    new_other_names = list(new_anchor_media.other_names or [])
    new_description = new_anchor_media.description
    new_cover_image = new_anchor_media.cover_image

    anchor_changed = new_anchor_mal_id != anime.mal_id
    # Split drift detection: the embedding only consumes title fields +
    # description, so a cover_image-only change shouldn't trigger a
    # ~50-100ms encode.
    embedding_drifted = anchor_changed or (
        anime.title != new_title
        or anime.name_eng != new_name_eng
        or anime.name_jap != new_name_jap
        or (anime.other_names or []) != new_other_names
        or anime.description != new_description
    )
    umbrella_drifted = embedding_drifted or anime.cover_image != new_cover_image

    if not reclassified and not umbrella_drifted:
        return None

    diff: ReclassifyDiff = {
        "reclassified": reclassified,
        "anchor_changed": anchor_changed,
        "umbrella_drifted": umbrella_drifted,
        "old_anchor_mal_id": anime.mal_id,
        "new_anchor_mal_id": new_anchor_mal_id,
    }

    if dry_run:
        return diff

    for mal_id, _old, new_rt in reclassified:
        current_by_mal[mal_id].relation_type = RelationType(new_rt)

    if umbrella_drifted:
        if embedding_drifted:
            # Regenerate BEFORE mutating the row so a regen failure
            # leaves both row and embedding consistent (same discipline
            # as anime_title_backfiller).
            await regenerate_anime_embedding(
                db, anime.id,
                title_texts=[new_title, new_name_eng, new_name_jap, *new_other_names],
                description_text=new_description or "",
            )
        anime.mal_id = new_anchor_mal_id
        anime.title = new_title
        anime.name_eng = new_name_eng
        anime.name_jap = new_name_jap
        anime.other_names = new_other_names
        anime.description = new_description
        anime.cover_image = new_cover_image

    return diff


def preview_reclassifications(
    anime_a: Anime, anime_b: Anime,
) -> list[tuple[Media, str, str]]:
    """Return per-media reclassifications that would land if `anime_a`
    absorbed `anime_b`'s media — as `(media, old_relation_type,
    new_relation_type)` tuples. Read-only; never mutates either anime.
    Powers the admin merge-candidate preview.

    Returns raw `(media, str, str)` tuples instead of a Pydantic schema
    so this domain helper stays decoupled from the admin response
    shape — the caller (merge_candidate_service.list_pending) maps to
    PendingReclassification.

    Requires both anime's `media` collection + each media's
    `relation_edges` sidecar to be pre-loaded by the caller.
    """
    combined_media = list(anime_a.media) + list(anime_b.media)
    nodes, edges = _build_classifier_graph(combined_media)
    classifications = classify_anime_relations(nodes, edges)
    media_by_mal = {m.mal_id: m for m in combined_media}

    out: list[tuple[Media, str, str]] = []
    for mal_id, new_rt in classifications.items():
        media = media_by_mal[mal_id]
        old_rt = media.relation_type.value
        if old_rt != new_rt:
            out.append((media, old_rt, new_rt))
    return out
