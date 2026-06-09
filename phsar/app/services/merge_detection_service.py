"""Detect potential duplicate anime via multiple signals.

Three detectors feed the merge_candidates table:

- title_studio: SequenceMatcher.ratio() OR containment >= 0.85, gated by
  studio overlap. Catches "Naruto" / "Naruto Shippuuden" — strong enough on
  its own.
- title_desc: weaker title match (>= 0.5) plus description-embedding cosine
  >= 0.85, also gated by studio overlap. Catches "Dr. Stone" / "Dr. Stone:
  New World" where the subtitle pushes the title score below the alone-rule.
- relation_link: a `media_relation_edges` sidecar entry points to media
  under a different anime via a strong-link relation (sequel, prequel,
  alternative_version). Strongest signal — MAL itself is asserting the
  connection. No score gate, no studio gate; admin still reviews.

`relation_link` reads the persisted sidecar table (single source of truth)
via `find_cross_anime_relation_pairs`. All three trigger sites — save,
update_sweep, backfill — converge through that helper so the signal fires
identically regardless of which job created the anime rows or when.

Detection is run from save_search_results (new × existing), from the
update_sweep finalization (changed × catalog), and from a startup +
admin-triggered backfill (catalog-wide). Tunables are deliberately
module-level — there's no use case for varying them per call.
"""

import logging
import re
from difflib import SequenceMatcher
from typing import NamedTuple

import numpy as np
from sqlalchemy.ext.asyncio import AsyncSession

from app.daos.merge_candidate_dao import MergeCandidateDAO
from app.services.relation_classifier import ALT_CHAIN_EDGES

logger = logging.getLogger(__name__)


class AnimeForDetection(NamedTuple):
    """Carrier for the per-anime data the detector compares against. Built
    once by the DAO so we don't re-fetch studios + embeddings per pair."""
    id: int
    title: str
    studios: set[int]
    description_embedding: list[float] | None

merge_candidate_dao = MergeCandidateDAO()

# Title-alone threshold. Either SequenceMatcher.ratio() OR containment
# (longest contiguous match / shorter length) crossing this is enough,
# provided studios overlap.
TITLE_ALONE_THRESHOLD = 0.85
# Title floor for the title+desc combined rule. Below this even a strong
# description match isn't trusted — random shows with vaguely similar
# synopses shouldn't flag.
TITLE_FLOOR_FOR_DESC = 0.5
# Description-cosine threshold for the title+desc combined rule.
DESC_THRESHOLD = 0.85
# Containment match must be at least this many chars to count, OR a full
# match of the shorter title with the shorter at least MIN_FULL_MATCH_CHARS
# long. Blocks one/two-letter substrings ('k' ⊂ 'knights') from scoring 1.0.
MIN_CONTAINMENT_MATCH_CHARS = 4
MIN_FULL_MATCH_CHARS = 3

DETECTOR_TITLE_STUDIO = "title_studio"
DETECTOR_TITLE_DESC = "title_desc"
DETECTOR_RELATION_LINK = "relation_link"

# Strong-link MAL relations that count as "these belong together" signals.
# Reuses the classifier's same-chain edge set: a relation that builds the
# main+alt chain inside an umbrella also unifies separately-scraped
# umbrellas. Weaker relations (spin-off, side_story, parent_story, summary,
# full_story, other) are MAL asserting "related but distinct" — adding
# them produces false positives (validated against the prod catalog).

# Conservative season-marker stripper. Keeps distinct franchises distinct;
# only collapses noise that doesn't disambiguate ("Season 2", "Part III").
_SEASON_PATTERNS = [
    re.compile(r"\bseason\s+\d+\b", re.IGNORECASE),
    re.compile(r"\b\d+(?:st|nd|rd|th)\s+season\b", re.IGNORECASE),
    re.compile(r"\bpart\s+\d+\b", re.IGNORECASE),
    re.compile(r"\b(?:i{1,3}|iv|v|vi{0,3}|ix|x)\b$", re.IGNORECASE),
]


def normalize_title(title: str) -> str:
    """Lowercase + strip season/part markers + collapse whitespace.

    Conservative on purpose: aggressive normalization (NFKD, punctuation
    stripping) tends to merge genuinely distinct titles that share a stem.
    """
    s = title.lower().strip()
    for pat in _SEASON_PATTERNS:
        s = pat.sub("", s)
    return re.sub(r"\s+", " ", s).strip()


def _is_word_boundary_match(longer: str, start: int, size: int) -> bool:
    """True iff the substring [start, start+size) sits at word boundaries
    on both sides of `longer`. A boundary is start/end-of-string or a
    non-alphanumeric neighbor character. Used to reject spurious containment
    matches like 'k' ⊂ 'knights' where the match runs into another word."""
    left_ok = start == 0 or not longer[start - 1].isalnum()
    right_ok = start + size == len(longer) or not longer[start + size].isalnum()
    return left_ok and right_ok


def _title_score(a: str, b: str) -> float:
    """max(ratio, containment) — symmetric ratio catches near-equal titles
    while containment (longest contiguous match / shorter length) catches
    'X' ⊂ 'X: Subtitle'. Length-symmetric ratio under-counts the second
    case because half its denominator is the longer string.

    Containment is gated by a word-boundary check on the longer string and
    a minimum match-size floor (>= 4 chars, OR a full match where the
    shorter title is itself >= 3 chars). Without these, a one-letter title
    like 'K' would score containment 1.0 against any title containing the
    letter k.
    """
    if not a or not b:
        return 0.0
    seq = SequenceMatcher(None, a, b)
    ratio = seq.ratio()
    match = seq.find_longest_match(0, len(a), 0, len(b))
    containment = 0.0
    if match.size > 0:
        longer, longer_start = (a, match.a) if len(a) >= len(b) else (b, match.b)
        min_len = min(len(a), len(b))
        size_floor_ok = (
            match.size >= MIN_CONTAINMENT_MATCH_CHARS
            or (match.size == min_len and min_len >= MIN_FULL_MATCH_CHARS)
        )
        if size_floor_ok and _is_word_boundary_match(longer, longer_start, match.size):
            containment = match.size / min_len
    return max(ratio, containment)


def _cosine_similarity(a, b) -> float:
    """Cosine similarity of two embedding vectors. Returns 0.0 if either
    vector is empty/None or has zero norm. Uses numpy (already a transitive
    dep via sentence-transformers) so the O(catalog²) backfill doesn't
    spend its time in a Python float-loop on 384-dim arrays."""
    if a is None or b is None:
        return 0.0
    a_arr = np.asarray(a, dtype=np.float32)
    b_arr = np.asarray(b, dtype=np.float32)
    if a_arr.size == 0 or a_arr.shape != b_arr.shape:
        return 0.0
    norm_a = float(np.linalg.norm(a_arr))
    norm_b = float(np.linalg.norm(b_arr))
    if norm_a == 0.0 or norm_b == 0.0:
        return 0.0
    return float(np.dot(a_arr, b_arr) / (norm_a * norm_b))


async def _flag_if_similar(
    db: AsyncSession,
    a: AnimeForDetection,
    b: AnimeForDetection,
    seen_pairs: set[tuple[int, int]],
    norm_cache: dict[int, str],
) -> bool:
    """Apply the title-alone rule, then the title+desc combined rule.
    Studio overlap gates both. Returns True if a new candidate row was
    inserted. Updates seen_pairs and norm_cache in place."""
    pair = (a.id, b.id) if a.id < b.id else (b.id, a.id)
    if pair in seen_pairs:
        return False
    if a.studios.isdisjoint(b.studios):
        return False
    norm_a = norm_cache.get(a.id)
    if norm_a is None:
        norm_a = normalize_title(a.title)
        norm_cache[a.id] = norm_a
    norm_b = norm_cache.get(b.id)
    if norm_b is None:
        norm_b = normalize_title(b.title)
        norm_cache[b.id] = norm_b
    title = _title_score(norm_a, norm_b)

    if title >= TITLE_ALONE_THRESHOLD:
        await merge_candidate_dao.upsert_pending(
            db,
            anime_a_id=pair[0], anime_b_id=pair[1],
            similarity_score=title, detected_by=DETECTOR_TITLE_STUDIO,
        )
        seen_pairs.add(pair)
        logger.info(
            "Flagged (title_studio): '%s' (id=%d) vs '%s' (id=%d) title=%.3f",
            a.title, a.id, b.title, b.id, title,
        )
        return True

    if title >= TITLE_FLOOR_FOR_DESC:
        desc = _cosine_similarity(a.description_embedding, b.description_embedding)
        if desc >= DESC_THRESHOLD:
            # Combined score: weighted average so the stored similarity
            # roughly reflects the strength that triggered the flag, not
            # just the title or just the description in isolation.
            combined = 0.4 * title + 0.6 * desc
            await merge_candidate_dao.upsert_pending(
                db,
                anime_a_id=pair[0], anime_b_id=pair[1],
                similarity_score=combined, detected_by=DETECTOR_TITLE_DESC,
            )
            seen_pairs.add(pair)
            logger.info(
                "Flagged (title_desc): '%s' (id=%d) vs '%s' (id=%d) "
                "title=%.3f desc=%.3f",
                a.title, a.id, b.title, b.id, title, desc,
            )
            return True

    return False


async def detect_merge_candidates(
    db: AsyncSession,
    new_anime_ids: list[int],
    cross_link_pairs: list[tuple[int, int]] | None = None,
) -> int:
    """Compare each newly saved anime against the existing catalog AND
    against other newly saved anime, and insert pending merge candidates.

    Detection runs new × existing and new × new — not existing × existing
    (those would have been flagged on their own save, or are picked up by
    the startup `backfill_merge_candidates`). The new × new pass covers
    the common case where a single user scrape's top-N title search returns
    two near-duplicates that both land as separate anime in the same job;
    without it admin would have to wait for a container restart to see
    them. `_flag_if_similar`'s studio-overlap + title threshold gates filter
    genuine parent+sequel pairs that just happen to be saved together —
    when those do flag, admin dismisses once and the seen-pairs set keeps
    them dismissed.

    `cross_link_pairs` carries the relation_link signal — pairs flag with
    detected_by="relation_link" regardless of title or studio similarity,
    MAL is asserting the connection. Callers derive these from sidecars
    via `find_cross_anime_relation_pairs`.

    Returns the number of *new* rows inserted across all detectors. Pairs
    that already have a row (pending, dismissed, merged) are skipped before
    any signal computation, so admin's prior decisions survive re-detection.
    """
    if not new_anime_ids and not cross_link_pairs:
        return 0

    seen_pairs = await merge_candidate_dao.get_existing_pairs(db)
    inserted = 0

    # Relation-graph cross-links: highest-trust signal, no score gate.
    for new_id, existing_id in cross_link_pairs or []:
        pair = (new_id, existing_id) if new_id < existing_id else (existing_id, new_id)
        if pair in seen_pairs:
            continue
        await merge_candidate_dao.upsert_pending(
            db,
            anime_a_id=pair[0], anime_b_id=pair[1],
            similarity_score=1.0, detected_by=DETECTOR_RELATION_LINK,
        )
        seen_pairs.add(pair)
        inserted += 1
        logger.info(
            "Flagged (relation_link): new id=%d vs existing id=%d",
            new_id, existing_id,
        )

    if not new_anime_ids:
        return inserted

    new_id_set = set(new_anime_ids)
    catalog = await merge_candidate_dao.get_anime_for_detection(db)
    if not catalog:
        return inserted

    new_entries: list[AnimeForDetection] = []
    existing_entries: list[AnimeForDetection] = []
    for entry in catalog:
        if entry.id in new_id_set:
            new_entries.append(entry)
        else:
            existing_entries.append(entry)

    if not new_entries:
        return inserted

    norm_cache: dict[int, str] = {}
    for new_entry in new_entries:
        if not new_entry.studios:
            continue
        for existing_entry in existing_entries:
            if await _flag_if_similar(db, new_entry, existing_entry, seen_pairs, norm_cache):
                inserted += 1

    # New × new: a single scrape can produce two anime that should have
    # been one. Use index-paired iteration so each unordered pair is
    # considered exactly once.
    for i, a in enumerate(new_entries):
        if not a.studios:
            continue
        for b in new_entries[i + 1:]:
            if await _flag_if_similar(db, a, b, seen_pairs, norm_cache):
                inserted += 1

    return inserted


async def backfill_merge_candidates(db: AsyncSession) -> int:
    """One-shot detection over the existing catalog at startup AND on demand
    via the admin endpoint. Flags pairs the detector wasn't around for when
    they were first saved, plus any catalog-wide relation_link pairs the
    save/sweep paths missed.

    Idempotent across restarts: pre-fetches the existing pair set and skips
    those pairs entirely, so the per-startup cost is O(catalog²) of the
    studio-overlap and similarity checks only on previously unflagged
    pairs. Once admin has reviewed the first wave, subsequent restarts do
    almost no work.

    Runs all three signals here, including a full-catalog relation_link
    sidecar sweep — surfaces strong-link pairs whose constituent anime
    were never co-located in any live scrape.

    Caller-commits at the end so the seeder loop in lifespan stays consistent
    with the other backfillers.
    """
    catalog = await merge_candidate_dao.get_anime_for_detection(db)
    if len(catalog) < 2:
        return 0

    seen_pairs = await merge_candidate_dao.get_existing_pairs(db)
    norm_cache: dict[int, str] = {}
    inserted = 0
    for i in range(len(catalog)):
        a = catalog[i]
        if not a.studios:
            continue
        for j in range(i + 1, len(catalog)):
            b = catalog[j]
            if await _flag_if_similar(db, a, b, seen_pairs, norm_cache):
                inserted += 1

    cross_link_pairs = await find_cross_anime_relation_pairs(db)
    if cross_link_pairs:
        inserted += await detect_merge_candidates(
            db, new_anime_ids=[], cross_link_pairs=cross_link_pairs,
        )

    if inserted:
        await db.commit()
        logger.info("Merge-candidate backfill flagged %d new pair(s)", inserted)
    return inserted


async def find_cross_anime_relation_pairs(
    db: AsyncSession,
    *,
    scope_anime_ids: list[int] | None = None,
) -> list[tuple[int, int]]:
    """Pins the `ALT_CHAIN_EDGES` allowlist for the relation_link signal so
    save, sweep, and backfill paths don't thread the policy through every
    site. See DAO method for query implementation."""
    return await merge_candidate_dao.get_cross_anime_relation_pairs(
        db,
        scope_anime_ids=scope_anime_ids,
        allowed_relations=ALT_CHAIN_EDGES,
    )
