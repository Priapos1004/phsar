---
tags: [jikan, mal, scraping, bfs, rate-limit, retry, donghua, error-handling]
category: reference
---

# Jikan / MAL Scraper Quirks & Field Notes

**Date:** 2026-05-11 (initial) | **Owners:** `phsar/app/services/jikan_scraper.py`, `phsar/app/services/search_service.py`, `phsar/app/services/scrape_dispatcher.py`

## Summary

Field notes on Jikan v4 (and the MAL data underneath it) accumulated through v0.13.x → v0.14.0. This is the place to record MAL data quirks, rate-limit lessons, BFS edge cases, and failure modes — anything where the *implementation choice* is non-obvious from the code alone. Append findings here as they're discovered; cross-link to the change/commit that surfaced them.

The corresponding production code lives in three layers:

- **`jikan_scraper.py`** — HTTP client + tenacity retry + class-level rate-limit gate + the BFS algorithm itself (`search_title`).
- **`search_service.py`** — orchestrates BFS, normalizes outputs, handles attach-to-existing / promote-root fallbacks, runs DB-side dedupe.
- **`scrape_dispatcher.py`** — invokes the above as a background job and translates failures into user-visible error categories.

## Failed Approaches

- **Rate limit at 0.35s (~2.85 req/s).** Within Jikan's documented 3 req/s burst but observed 429s in practice on `/seasons/now` pagination and seasonal-sweep child BFS runs. The binding constraint is the **per-minute** ceiling (60 req/min), not the per-second burst. Never do: set spacing based on the burst ceiling for continuous-request workloads.
- **Rate limit at 0.5s (~2 req/s).** Same outcome. Even 2 req/s exceeds 60/min sustained over a minute window. Never do: assume "well under 3 req/s" is safe without computing the rolling-minute total.
- **Placeholder titles in MediaUnwanted** (e.g., `<mal_id:NNNN>`) for entries where MAL returned `title=null`. Permanently blacklisting a transient null-title pollutes the admin-only table with garbage strings AND blocks rediscovery once MAL fills in the title. Never do: blacklist on transient MAL data states — distinguish "MAL hasn't finished populating this row yet" from "we deliberately don't want this kind of media."
- **Walking `Alternative Setting` relations.** Treating it like Sequel/Prequel/Side Story conflates separate franchises that just share themes (Zhe Tian ↔ Wanmei Shijie, Madoka Magica ↔ Magia Record). The BFS walks both worlds into one Anime row and the merge detector then flags false positives on every sweep. Never do: expand `alternative_setting`; treat it as a graph boundary (like `crossover`, but without recording the node either — alt-settings are explicit "different story" labels).
- **`is_main_story` gated only on `TV`/`Movie`.** Brand-new donghua sub-universes whose canonical main is an ONA produce a graph with no main → `MainMediaNotFoundError` → seasonal-sweep child fails for the whole franchise. Never do: assume `TV`/`Movie` covers the canonical-main case for non-Japanese MAL entries. (We didn't fix the gate itself — instead added a `_pick_root_for_promotion` fallback. See Key Decisions.)
- **`AnimeNotFoundError` for empty 200 responses.** When MAL returns `{"data": null}` or `{"data": {}}` (transient hiccup; observed for valid mal_ids), the old code raised `AnimeNotFoundError`, a `PermanentPhsarError` → `retryable=False` → bell hides retry → user locked out for the 72h dedupe window. A real 404 is `HTTPStatusError` from `_get`, which is correctly permanent. The empty-data case is transient and deserves `TransientUpstreamError` (retryable). Never do: conflate "MAL returned no row" with "MAL returned no data this time."
- **Not retrying 429.** At a sustained 1 req/s rate with no headroom under MAL's 60 req/min, a brief per-minute-window overrun produces a 429 even though the average rate is correct. Not retrying = a single 429 kills the whole job. Never do: treat 429 like other 4xx; 429 is the one 4xx with a "wait and retry" semantic baked into HTTP. (Counterpoint: at *higher* request rates, retrying 429 masks sustained abuse — see Key Decisions for how we cap.)
- **Re-enqueue check at the bottom of the BFS loop body.** The original BFS had `if not left_mal_ids and mal_id not in visited_ids: re-enqueue` as the last statement inside the `while` body. When the last popped node hit a `continue` path (visited / excluded / null-title / filtered), the check was bypassed. For franchises whose only relation is `Other` and no node points back (Rilakkuma → Pocket no Naka), the dropped seed was never recovered and the graph ended without a main story. Never do: put a recovery check below a `continue` boundary without an explicit post-loop net.
- **MediaUnwanted entries as cross-link signal.** When the BFS reached an excluded mal_id and added it to `cross_link_mal_ids` for the merge detector, it didn't distinguish "this lives in Media under some anime" (real cross-link) from "this lives in MediaUnwanted" (filtered, no parent). The attach-to-existing fallback then tried to attach a graph to a Music/PV/CM with no parent Anime; the attach silently no-op'd; the dispatcher then raised `MainMediaNotFoundError` instead of trying the promote-root fallback. Never do: trust raw `excluded_mal_ids` membership as a franchise-overlap signal.

## Key Decisions

- **Rate limit `_MIN_REQUEST_INTERVAL_S = 1.0`** (1 req/s) for continuous-request flows. Matches Jikan's *sustained* 60 req/min, not the *burst* 3 req/s. Trade-off: a 200-anime sweep takes ~3-5 min instead of ~1 min, but no 429s and no IP-ban risk. Class-level lock so multiple `JikanScraper()` instances share the gate.
- **Asymmetric retry budget** via `_stop_strategy`. 429: 3 total attempts (2 retries — enough to bridge a misaligned per-minute window, not enough to mask sustained throttling). 5xx / timeout / network: 5 attempts. Other 4xx (404, etc.): not retried (deterministic). The 429 cap is deliberate — if MAL is sustained-rate-limiting us, retrying harder doesn't fix it; the right response is to slow the source rate.
- **Null titles → silent skip** (same sentinel pattern as `Not yet aired` + `media_type=None`). MAL routinely leaves `title=null` on entries it's still populating (romanization pending for Chinese/Korean shows, brand-new PV stubs); the field reliably fills within hours. We skip the entry from the BFS without adding to MediaUnwanted, so the next sweep gets another chance.
- **`alternative setting` as a graph boundary cut.** The relation is *enqueued* alongside `adaptation` — we never walk it. (Note: the literal in the code uses a SPACE (`"alternative setting"`), not the underscore form some other checks use. See Gotchas.)
- **`_pick_root_for_promotion` fallback** in `search_service.search_mal_api`. When `get_first_main_relation` raises AND `seed_mal_id` is set AND there's no single cross-link, pick the most main-like entry by `(type_tier, aired_from)` where TV/Movie=0, ONA=1, OVA/TVSpecial=2, Special=3 (nulls last on aired_from). Promotes that entry to `relation_type="main"` and saves the graph as a new Anime. Handles donghua sub-universes (whose canonical main is ONA) cleanly; also handles the pilot-aired-before-the-real-show edge because tier > date.
- **Post-loop seed-recovery net** after the BFS `while` loop. When the seed was dropped via the `is_main_story + has_relations` branch AND no organic rediscovery happened AND the inline bottom-of-loop re-enqueue was bypassed by a `continue`, re-add the seed directly as `relation_type="main"` (the drop branch only fires when `is_main_story=True`, so this classification matches).
- **`unwanted_mal_ids` filter on cross-link signals.** `search_mal_api` subtracts MediaUnwanted entries from `cross_link_mal_ids` before the attach-vs-promote decision. MediaUnwanted entries aren't real franchise overlaps — they're filtered media with no parent Anime to attach to.
- **`AttachToExistingAction` schema for orphan-side-story graphs with a single cross-link to existing Media.** The dispatcher routes these through `attach_search_result_to_anime` (the same primitive 7c's freshness probe uses for tier-3 sweeps), attaching new media under the existing parent instead of saving as a duplicate Anime. Closes the tier-1/tier-2 parent gap where the probe doesn't run.
- **`TransientUpstreamError(PhsarBaseError)`** distinct from `PermanentPhsarError`. Empty-200 MAL responses surface as transient so the bell offers retry. `_classify_error` in `job_worker` also tags it as `upstream_outage` for friendly bell copy.
- **`AnimeFilteredOutError(PermanentPhsarError)`** distinct from `AnimeNotFoundError`. When the dispatcher sees `results == []` after a seeded BFS AND `MediaUnwantedDAO.get_by_mal_id(seed)` returns a row, the seed was filtered as Music/PV/CM/Hentai — surface that explicitly. Admin sees `"'X' was filtered out as PV"` in `jobs.failed` instead of the misleading `"Anime titled X not found"`.
- **`MainMediaNotFoundError` surfaced honestly** when a seeded BFS finds the entry but can't anchor it (no main in graph AND no single cross-link AND no MediaUnwanted match). Previously fell through to `AnimeNotFoundError`, which implied MAL had no record at all.
- **Crossover is kept, alt-setting is cut.** Both label franchise boundaries, but crossover anime *are* legitimately part of multiple franchises (a Fate × Tsukihime crossover belongs to both worlds). Record crossover nodes in the graph with `relation_type="crossover"`; stop expanding from them. Alt-setting anime are *not* in the same franchise — drop them entirely.

## Gotchas & Learnings

### MAL data quirks

- **`title=null` is transient.** Sampled the 100 newest MAL entries during validation and found zero null titles. The failures we observed earlier hit nulls that MAL populated within hours (likely the romanization pipeline lagging behind the entry creation). When the BFS sees null title, silent-skip and trust the next sweep.
- **Empty 200 OK ≠ 404.** MAL occasionally returns `{"data": null}` or `{"data": {}}` for a valid mal_id (a known case: `/anime/64060` in our validation). This is distinct from a real 404 (which raises `HTTPStatusError`). Treat empty data as transient (`TransientUpstreamError`), not permanent.
- **`alternative_setting` ≠ same franchise.** This relation labels separate stories that share themes/setting (e.g., Madoka Magica ↔ Magia Record share the magical-girl framework but are different shows). Always treat as a graph boundary.
- **`Other` relations aren't reciprocal.** Many franchises link only forward via `Other` (Rilakkuma → "Rilakkuma to Kaoru-san") with no back-pointer. Combined with the seed-drop branch, this means the BFS can lose the seed entirely without the post-loop net.
- **Crossover anime exist as standalone MAL entries.** They link to multiple franchises via `Crossover` relations. Don't traverse the crossover boundary, but DO record the node in the graph.
- **Per-minute window is enforced tightly.** Even at exactly 60 req/min average, a brief micro-burst (e.g., variability in the request scheduler) puts you over for a few hundred ms and triggers 429.
- **Jikan upstream is MAL.** The Jikan docs explicitly state "It's still possible to get rate limited from MyAnimeList.net instead" — even when our rate is fine for Jikan, MAL might throttle us independently. The 429 retry policy hedges against both.

### Relation string format

- **MAL emits relation strings with SPACES and CamelCase**: `"Side Story"`, `"Alternative Setting"`, `"Parent story"`, `"Full story"`, `"Spin-Off"`. The scraper normalizes them once on entry via `_normalize_relation(rel) = rel.lower().replace(" ", "_")`, so every downstream comparison works against the underscore form.
- **Why the normalization matters (regression from v0.13.x → fixed in v0.14.0).** The `is_main_story` gate excludes any popped TV/Movie node whose relations list contains `"parent_story"` or `"full_story"`. Before the fix the list was built from raw MAL strings (`"Parent story"`), so both `not in` checks always passed and any TV/Movie with a `Parent story` upward link silently classified as `main`. In practice every Naruto/Bleach/Demon Slayer movie ended up as a separate `main` row instead of `side_story` under its parent series. The Naruto-shaped fixture in `test_search_title_normalizes_relation_strings_so_franchise_movies_are_side_story` is the regression guard.
- **Fix is for new scrapes only.** The sweep's relations probe goes through `attach_search_result_to_anime`, which doesn't reclassify existing `relation_type` values. Catalog rows scraped pre-fix keep their stale `main` labels until the parent anime is deleted and re-scraped. Document this in the upgrade notes for the next deploy; the alternative (data migration that re-runs classification) is its own follow-up.

### BFS algorithm specifics

- **`is_main_story` only applies to the seed.** The check requires `current_relation is None`, which is true only for the first popped node. Other nodes get their relation_type from the `Sequel`/`Side Story`/etc. label that put them in the queue.
- **Drop-and-rediscover dance.** When the seed is_main_story AND has relations, the BFS deliberately removes it from `visited_ids`, `all_info`, and the graph, expecting BFS to walk back through a relation pointing TO the seed (Sequel → seed, Side Story → seed, etc.). When that works, the seed gets a fresh classification in the second pass. When it doesn't (Rilakkuma case — only outgoing `Other`), the post-loop net catches it.
- **The seed re-enqueue check inside the loop is bypassed by `continue` paths.** Pre-fix it sat at the bottom of the loop body and only fired when the iteration ran to completion. The post-loop net at the end of the BFS is the safety belt.
- **`Character` relations are skipped entirely.** Not even recorded — they typically link unrelated anime via shared characters (e.g., a "No More Eiga Dorobou" anti-piracy spot linked from every show that played the spot). Useful for fan navigation, useless for franchise graphing.
- **`Adaptation` is skipped** because adaptations are usually manga/LN (the BFS already filters by `type=anime`, so this is belt-and-braces).

### Failure-mode taxonomy

The dispatcher distinguishes four post-empty-result paths:

| Cause | Detected via | Surface |
|---|---|---|
| Seed was Music/PV/CM/Hentai | `MediaUnwantedDAO.get_by_mal_id(seed_mal_id)` returns row | `AnimeFilteredOutError("'X' was filtered out as Music")` |
| MAL returned empty 200 | Caught earlier in `search_title` | `TransientUpstreamError("MAL returned no data for mal_id=N")` |
| Graph has no main + no single cross-link | Promote-root fallback didn't pick up | `MainMediaNotFoundError("Couldn't identify a main story for 'X'")` |
| No new match (no seed_mal_id mode, fuzzy query) | `results == []` from title search after catalog + MediaUnwanted filtering | `AnimeNotFoundError("No new anime matched 'X' on MAL")` |

This taxonomy was learned empirically — earlier validation runs surfaced jobs in `failed` state with misleading copy that made it hard to tell *which* failure mode hit. The dispatcher's `if not results and not attached_count:` ladder is the lookup table.

### Concurrency / isolation

- **Per-anime commit in `update_sweep_dispatcher`** but **bulk insert in `seasonal_sweep_dispatcher`**. The freshness sweep does MAL I/O per anime; per-anime commit preserves work on crash. The seasonal sweep's enqueue loop does no MAL I/O (already drained in the `fetch_current_season` step); a single `add_all` + commit shortens the maintenance window and the crash-safety argument doesn't apply.
- **Class-level rate lock means concurrent `JikanScraper()` instances share the gate.** If user_scrape and update_sweep ever ran concurrently (currently serialized by single-worker), they'd correctly throttle together at 1 req/s combined. Don't naively parallelize.

## Future Work

- **Backfill relation_type for catalog rows scraped pre-fix.** The normalization in v0.14.0 corrects `relation_type` for new scrapes only — the sweep's relations probe doesn't rewrite the field. Existing franchise movies/OVAs stay labeled `main` until their parent anime is deleted and re-scraped. A one-shot reclassification migration would re-run `get_relation_type` against existing media graphs. Out of scope for v0.14.0 because it needs its own validation pass against the live catalog.
- **`is_main_story` should include ONA when no parent_story/full_story.** Today, ONA seeds fall through to the promote-root fallback. Making the gate accept ONA + no-parent-story would let donghua land in the regular `save_search_results` flow without needing the fallback. Same outcome, cleaner code path.
- **Track null-title skip frequency per mal_id.** If a mal_id keeps coming back null over months, MAL likely won't ever populate it. After N silent-skips, add to MediaUnwanted with reason=`"NullTitle"` to prevent infinite re-fetch. Threshold to be determined empirically.
- **Distinguish "Music PV linked from main TV show" from standalone Music/PV/CM.** The former is part of a franchise (worth attaching as media under the main anime); the latter is unwanted. Currently both go to MediaUnwanted. Heuristic: a Music/PV/CM reached via a Parent Story or Side Story relation FROM a non-Music main anime *might* be franchise media. Needs careful design — false positives pollute the catalog with promotional clips.
- **Surface `attached_count` in the bell.** Today `result_summary.attached_count` is only visible by querying the `jobs` table directly. For user-initiated scrapes that end up attaching to an existing anime (rare but happens), the bell shows the cryptic `{anime_count: 0, media_count: 0}` instead of `"Attached 1 media to existing anime"`.
- **MAL might support 429 `Retry-After` headers.** Currently we ignore the header and use tenacity's exponential backoff. Check if MAL/Jikan emits a header; if so, honor it for tighter recovery on a true sustained-throttle event.

## Append-here template

When adding a new finding:

```markdown
### <date> — <one-line summary>

**Context:** what code path / commit / job uuid surfaced this
**Finding:** the quirk, with a concrete reproducer if possible
**Fix:** how we handled it (or "deferred, see Future Work")
**Code:** file:line of the relevant guard / fallback
```
