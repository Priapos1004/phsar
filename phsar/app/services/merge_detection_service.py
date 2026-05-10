"""Detect potential duplicate anime via multiple signals.

Three detectors feed the merge_candidates table:

- title_studio: SequenceMatcher.ratio() OR containment >= 0.85, gated by
  studio overlap. Catches "Naruto" / "Naruto Shippuuden" — strong enough on
  its own.
- title_desc: weaker title match (>= 0.5) plus description-embedding cosine
  >= 0.85, also gated by studio overlap. Catches "Dr. Stone" / "Dr. Stone:
  New World" where the subtitle pushes the title score below the alone-rule.
- relation_link: BFS during a save discovered a non-crossover related media
  that already lives under a different anime in the catalog. Strongest
  signal — MAL itself is asserting the connection. No score gate, no studio
  gate; admin still reviews.

Detection is run from save_search_results (new × existing) and from a
startup backfiller (existing × existing). Tunables are deliberately
module-level — there's no use case for varying them per call.
"""

import logging
import re
from difflib import SequenceMatcher
from typing import NamedTuple

import numpy as np
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.daos.merge_candidate_dao import MergeCandidateDAO
from app.models.anime import Anime
from app.models.media import Media

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
    """Compare each newly saved anime against the existing catalog and
    insert pending merge candidates.

    Detection runs new × existing only — not new × new (avoids self-flagging
    related anime saved in the same scrape) and not existing × existing
    (those would have been flagged on their own save).

    `cross_link_pairs` carries the relation-graph signal from the BFS:
    pairs (new_anime_id, existing_anime_id) where MAL says the new anime is
    related to the existing one through a non-crossover relation. Those
    flag with detected_by="relation_link" regardless of title or studio
    similarity — MAL is asserting the connection.

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

    if not new_entries or not existing_entries:
        return inserted

    norm_cache: dict[int, str] = {}
    for new_entry in new_entries:
        if not new_entry.studios:
            continue
        for existing_entry in existing_entries:
            if await _flag_if_similar(db, new_entry, existing_entry, seen_pairs, norm_cache):
                inserted += 1
    return inserted


async def backfill_merge_candidates(db: AsyncSession) -> int:
    """One-shot detection over the existing catalog at startup. Flags pairs
    the detector wasn't around for when they were first saved.

    Idempotent across restarts: pre-fetches the existing pair set and skips
    those pairs entirely, so the per-startup cost is O(catalog²) of the
    studio-overlap and similarity checks only on previously unflagged
    pairs. Once admin has reviewed the first wave, subsequent restarts do
    almost no work.

    The relation_link signal is not produced here — it requires live BFS
    state from a scrape. Backfill uses title_studio + title_desc only.

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

    if inserted:
        await db.commit()
        logger.info("Merge-candidate backfill flagged %d new pair(s)", inserted)
    return inserted


async def resolve_cross_link_pairs(
    db: AsyncSession,
    new_anime_id: int,
    cross_link_mal_ids: set[int],
) -> list[tuple[int, int]]:
    """Map (new_anime_id, mal_id) → (new_anime_id, owning_anime_id) by
    looking up which existing anime owns each cross-linked media mal_id.

    Pairs with the new anime itself (the BFS may have surfaced a media that
    we're about to attach to the new anime) are filtered — only return
    pairs where the cross-linked media currently lives under a *different*
    anime."""
    if not cross_link_mal_ids:
        return []
    stmt = (
        select(Media.mal_id, Anime.id)
        .join(Anime, Anime.id == Media.anime_id)
        .where(Media.mal_id.in_(cross_link_mal_ids))
    )
    result = await db.execute(stmt)
    pairs: list[tuple[int, int]] = []
    for _mal_id, anime_id in result.all():
        if anime_id != new_anime_id:
            pairs.append((new_anime_id, anime_id))
    return pairs
