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
)
from app.services.vector_embedding_service import regenerate_anime_embedding


def build_classifier_graph(
    media: Iterable[Media],
) -> tuple[dict[int, dict], list[tuple[int, int, str]]]:
    """Project a media iterable into (nodes, edges) ready for
    `classify_anime_relations`. Edges include the full unfiltered set
    from each media's sidecar — the classifier filters dangling
    endpoints at `_build_adjacency` time. This shape lets merge time
    surface bridge edges that were previously dangling at scrape time
    (Dr. Stone split-merge case).
    """
    media_list = list(media)
    nodes = {m.mal_id: media_to_classifier_node(m) for m in media_list}
    edges: list[tuple[int, int, str]] = []
    for m in media_list:
        if m.relation_edges is None:
            continue
        for target_mal_id, rel in m.relation_edges.edges:
            edges.append((m.mal_id, target_mal_id, rel))
    return nodes, edges


class UmbrellaFieldChange(TypedDict):
    field: str
    old: object
    new: object


class ReclassifyDiff(TypedDict):
    reclassified: list[tuple[int, str, str]]  # (mal_id, old_rt, new_rt)
    anchor_changed: bool
    # True if any of the 7 umbrella fields differs from the anchor
    # media's current value (anchor_changed implies this).
    umbrella_drifted: bool
    old_anchor_mal_id: int
    new_anchor_mal_id: int
    # Per-field old → new for the umbrella fields that drifted. The
    # update_sweep dispatcher surfaces these on its detail page so the
    # admin can see exactly which umbrella field MAL moved without
    # re-deriving from the row.
    umbrella_field_changes: list[UmbrellaFieldChange]
    # True iff drift triggered an AnimeSearch embedding regen — distinct
    # from `umbrella_drifted` because a cover_image-only change rewrites
    # the row without re-encoding.
    embedding_regenerated: bool


async def reclassify_anime(
    db: AsyncSession, anime: Anime, *, dry_run: bool = False,
) -> ReclassifyDiff | None:
    """Re-classify all media under `anime` and rewrite the umbrella row
    if the canonical anchor or any of the 7 umbrella fields drifted.
    Returns `None` when no changes are needed; otherwise a diff dict.
    Caller commits.
    """
    nodes, edges = build_classifier_graph(anime.media)
    classifications, new_anchor_mal_id = classify_anime_relations(nodes, edges)
    assert new_anchor_mal_id is not None, "non-empty nodes always yield an anchor"

    current_by_mal = {m.mal_id: m for m in anime.media}
    reclassified: list[tuple[int, str, str]] = []
    for mal_id, new_rt in classifications.items():
        old_rt = current_by_mal[mal_id].relation_type.value
        if old_rt != new_rt:
            reclassified.append((mal_id, old_rt, new_rt))

    # Mirrors create_anime_from_media's field copy + strip so the
    # post-rewrite anime row looks identical to one scraped fresh from
    # this anchor. Dict-driven so adding an 8th umbrella field (or
    # changing which fields gate embedding regen) is one edit, not three.
    new_anchor_media = current_by_mal[new_anchor_mal_id]
    new_umbrella: dict[str, object] = {
        "mal_id": new_anchor_mal_id,
        "title": strip_season_suffix(new_anchor_media.title) or new_anchor_media.title,
        "name_eng": strip_season_suffix(new_anchor_media.name_eng),
        "name_jap": strip_season_suffix(new_anchor_media.name_jap, japanese=True),
        "other_names": list(new_anchor_media.other_names or []),
        "description": new_anchor_media.description,
        "cover_image": new_anchor_media.cover_image,
    }
    # Fields the AnimeSearch embedding consumes — a cover_image-only
    # change shouldn't trigger the ~50-100ms encode.
    _EMBEDDING_FIELDS = ("mal_id", "title", "name_eng", "name_jap", "other_names", "description")

    def _current(field: str) -> object:
        # Normalize other_names None → [] so the comparison matches
        # how new_umbrella["other_names"] is built.
        val = getattr(anime, field)
        return list(val or []) if field == "other_names" else val

    def _drifted(field: str, new_val: object) -> bool:
        current = _current(field)
        # MAL's title_synonyms list isn't returned in stable order, so
        # comparing as ordered lists would flag pure reorders as drift
        # — and the per-anchor change would then cascade into an
        # AnimeSearch embedding regen on noise.
        if field == "other_names":
            return set(current) != set(new_val)
        return current != new_val

    drifted_fields = {f for f, v in new_umbrella.items() if _drifted(f, v)}
    umbrella_drifted = bool(drifted_fields)
    embedding_drifted = bool(drifted_fields & set(_EMBEDDING_FIELDS))
    anchor_changed = "mal_id" in drifted_fields

    if not reclassified and not umbrella_drifted:
        return None

    # Capture old → new BEFORE the row mutation so the dispatcher's
    # detail-page payload reflects what MAL actually shifted.
    umbrella_field_changes: list[UmbrellaFieldChange] = [
        {"field": f, "old": _current(f), "new": new_umbrella[f]}
        for f in drifted_fields
    ]

    diff: ReclassifyDiff = {
        "reclassified": reclassified,
        "anchor_changed": anchor_changed,
        "umbrella_drifted": umbrella_drifted,
        "old_anchor_mal_id": anime.mal_id,
        "new_anchor_mal_id": new_anchor_mal_id,
        "umbrella_field_changes": umbrella_field_changes,
        "embedding_regenerated": embedding_drifted and not dry_run,
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
                title_texts=[
                    new_umbrella["title"],
                    new_umbrella["name_eng"],
                    new_umbrella["name_jap"],
                    *new_umbrella["other_names"],
                ],
                description_text=new_umbrella["description"] or "",
            )
        for field, value in new_umbrella.items():
            setattr(anime, field, value)

    return diff


def umbrella_diff_to_log_entry(
    anime: Anime, diff: ReclassifyDiff,
) -> dict:
    """Serialize a ReclassifyDiff into the JSONB-bound shape the
    update_sweep result_summary's `anime_umbrella_changes` list expects.
    Owns the projection here so the dispatcher doesn't reach into
    ReclassifyDiff's TypedDict keys and so a future schema shift lands
    in one place."""
    return {
        "anime_id": anime.id,
        "anime_uuid": str(anime.uuid),
        "anime_title": anime.title,
        "anime_name_eng": anime.name_eng,
        "anime_name_jap": anime.name_jap,
        "fields": diff["umbrella_field_changes"],
        "anchor_changed": diff["anchor_changed"],
        "old_anchor_mal_id": diff["old_anchor_mal_id"],
        "new_anchor_mal_id": diff["new_anchor_mal_id"],
        "embedding_regenerated": diff["embedding_regenerated"],
        "reclassified": [
            {"mal_id": mal_id, "old": old, "new": new}
            for mal_id, old, new in diff["reclassified"]
        ],
    }


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
    nodes, edges = build_classifier_graph(combined_media)
    classifications, _ = classify_anime_relations(nodes, edges)
    media_by_mal = {m.mal_id: m for m in combined_media}

    out: list[tuple[Media, str, str]] = []
    for mal_id, new_rt in classifications.items():
        media = media_by_mal[mal_id]
        old_rt = media.relation_type.value
        if old_rt != new_rt:
            out.append((media, old_rt, new_rt))
    return out
