# Relations, merges and splits

How captured MAL edges become a franchise structure — which media is the "main"
story, which anime rows are duplicates, and which single row is secretly two
franchises.

**Code**: `services/relation_classifier.py` (pure, DB-less) →
`services/anime_relation_service.py` (orchestration) →
`services/merge_detection_service.py`, `services/merge_candidate_service.py`,
`services/split_candidate_service.py` (admin queues).

Three passes run at three sites: on scrape, on merge (over the consolidated set),
and in the relation backfiller (per catalogue row).

## Pass 1 — capture

The BFS records relation **edges** without classifying them (see
[scraping](scraping.md)). Edges persist unfiltered in the `media_relation_edges`
sidecar, including targets outside the local catalogue, so a bridge edge activates
later when the other side arrives.

`alternative_setting`, `character` and `adaptation` are dropped before capture.
`alternative_setting` is MAL's explicit "different story, shared themes" — folding
those into one anime row produced false-positive merge candidates on every sweep.

## Pass 2 — classify

`classify_anime_relations(nodes, edges)` picks an **anchor**, builds the main chain
by sequel/prequel closure, labels the alt chain via `alternative_version` edges,
and defaults everything else to `side_story`. A final layer demotes weak mains and
relabels recaps.

Relation types: `Main`, `Summary`, `SideStory`, `AlternativeVersion`.

**Anchor choice**: substance gate, then tier (TV > ONA > Movie > other), then oldest
`aired_from`.

### The substance gate

- TV/ONA: `episodes >= 8` and `duration_seconds >= 600`. A **NULL** episode count
  passes — a currently-airing or long-running series legitimately has no total
  (Conan, Anpanman, mid-arc donghua).
- Movie: `duration_seconds >= 1800`
- TVSpecial: strict — NULL episodes fails here, since a special with no count is an
  anomaly rather than an open-ended run.

**High-episode short-form waiver**: a TV/ONA entry under the per-episode duration
floor still passes when `episodes × duration_seconds >= 7600` (≈2h). Per-episode
length is a poor substance proxy for a short-form series — a 120-episode × 5.5-min
flagship season is ~11h of story. Only the *duration* floor is waived; the
8-episode floor still gates one-shots. The 7,600 threshold sits on a plateau
(~7,200–7,900) tuned against the production catalogue; below ~7,200 a later short
season sneaks over the floor while the shorter base season stays under, stealing
the anchor and titling the franchise after S4. **Re-validate against a fresh prod
dump before retuning.**

**Per-floor relaxation is scoped to the main chain.** The demotion loop relaxes a
floor that no aired *main-chain* member clears — a floor with no discriminating
power for this franchise. Computing that over all nodes lets an off-chain
full-length spin-off vote on whether a floor discriminates among the canonical
spine, which demotes genuinely-short main seasons. The scoping is monotonic
un-demote-only: a subset cannot clear more floors than the superset.

**Not-yet-aired entries** get a provisional pass on NULL duration/episodes —
unpublished metadata is not thinness, so an announced sequel stays Main. They are
**anchor-ineligible**, since a franchise cannot anchor on something unaired. A
*populated* short duration still fails, and this is deliberately not extended to
Currently Airing (an airing show normally has published duration, and including it
let a mid-franchise part steal the anchor).

**Recap demotion**: a main-chain non-anchor media declaring an outgoing
`full_story` edge ("my full story is elsewhere") is relabelled `summary`, ahead of
the substance check. The gate alone cannot catch a *full-length* recap film — a
~87-min recap movie clears the 30-min Movie floor. Relabel-only: it never touches
`main_chain`, so a genuine main reachable only *through* a recap stays main.

### Keep-decision waivers

Two waivers are consulted **only** by `would_be_dropped_as_weak_anchor` — never by
the substance gate, anchor pick, classifier, or split detector. That scoping is
what stops a popular short from stealing a franchise anchor or spawning a false
split.

- **Popularity** (`scored_by >= 10000`), covering two shapes: a short-duration
  series with the type and episode floors still enforced, and a short-run
  full-length series (`episodes >= 6` with the duration floor *met*) that the
  8-episode floor would reject.
- **Feature-length ONA**: `episodes == 1` and `duration_seconds >= 3600`. MAL
  labels many theatrical and streaming-original films as ONA rather than Movie, so
  a 99-minute film gets held to the 8-episode floor and vanishes from search. The
  60-min floor is deliberately stricter than the 30-min Movie gate, to admit
  genuine features rather than long one-shots.

## Pass 3 — split detection

`find_disjoint_franchises(nodes, edges, anchor)` finds substance-passing media
outside the anchor's main+alt closure that form their own connected sequel chain
(≥2 substance-passing members). It never auto-splits — it raises a
`split_candidate` for admin review.

**Movie-only clusters bridged via `parent_story` or `summary` stay quiet.** MAL is
asserting "these are child stories", so they are legitimate side-story chains, not
sibling franchises — a long-running detective franchise's movies trip the
disjoint-cluster detector through sequel chains between the movies themselves.
Clusters with TV-tier members are unaffected.

Detection is **skipped when the anchor itself fails the substance gate**: with no
meaningful main chain, any substance-passing sub-chain would be a false positive.
Real contamination re-detects when a strong-anchor sibling lands.

## Merge detection

Three signals feed `merge_candidates`:

- **`title_studio`** — SequenceMatcher ratio or containment ≥ 0.85, gated by studio
  overlap. Containment additionally needs a word boundary on both sides in the
  longer string, plus a 4-char size floor (or a full match where the shorter title
  is itself ≥ 3 chars).
- **`title_desc`** — a weaker title match plus description-embedding cosine ≥ 0.85.
- **`relation_link`** — the sidecar links one anime's media to media under a
  *different* anime through a strong-link relation.

**The sidecar is the single source of truth for `relation_link`.** The alternative
— ephemeral BFS state during a live scrape — misses any pair created by separate
scrape jobs, which is the common case for a TV series and its movie retellings
entering the catalogue weeks apart. The invariant: *if two catalogue anime have
media linked through an allowlisted relation, the next detection run proposes the
pair, regardless of job ordering or which wave created them.*

Strong links are an **allowlist** (`sequel`, `prequel`, `alternative_version`), not
a blocklist. Weaker MAL relations are MAL asserting "related but distinct", not
"duplicates" — treating any relation as evidence produces dozens of spurious
cross-anime edges. The allowlist is shared with the classifier's alt-chain edge
set, since both ask "does MAL say these belong together?". Extend with care.

All three signals converge in `detect_merge_candidates`, called from three sites
with identical semantics: on save (scope = new anime), on sweep (scope = every
step-1 success, broader than probe-attached because a refresh alone rewrites
sidecars and can surface a fresh pair), and on backfill (whole catalogue). A
`seen_pairs` pre-fetch short-circuits already-flagged and admin-resolved pairs
before any signal is computed, so a dismissal survives re-detection everywhere.

## Executing a merge or split

Each pending merge candidate carries `pending_reclassifications` — the per-media
changes that *would* land (substance-gate demotions, alt-version labels, anchor
flips), so the admin sees the consequence before clicking merge rather than after.

**Merge** re-parents B's media onto A, deletes B by cascade, reclassifies the
consolidated set, re-runs detection against the survivor, and recomputes the
spoiler cache. `keep_uuid` swaps which side survives — the DB invariant
`anime_a_id < anime_b_id` is unchanged, A/B is presentation only. A shared
`Media.mal_id` between the two sides **fails loud**: a global unique violation
needs a human.

**Split** verifies the classifier still picks the recorded anchor (raising
`SplitCandidateStaleError` if MAL data shifted since detection), creates one anime
per cluster, re-parents media by FK assignment, expires the source's cached
collection, reclassifies both sides, then re-runs split *and* merge detection on
the results — a freshly-split franchise may match an existing parallel row.

**Rating safety**: media UUIDs are stable across re-parenting, so every
`Ratings.media_id` stays attached to the same media. Only the anime aggregation
shifts.

---

**Why it is this way**
- [Classifier redesign](../../compound-docs/2026-05-16-v0.14.1-search-and-data-fixes.md) — the two-pass design
- [Split candidates](../../compound-docs/2026-05-18-v0.14.2-split-candidates.md) — the third pass and TERMINAL edge capture
- [Scraper quirks](../../compound-docs/2026-05-11-jikan-scraper-quirks.md) — relation-label normalization
- [MAL API v2 migration](../../compound-docs/2026-07-18-v0.14.14-mal-api-migration.md) — substance-gate waivers
