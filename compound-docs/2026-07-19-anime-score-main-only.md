---
tags: [weighted-score, relation-type, score-top-percent, prod-data-analysis, anime-aggregation, spoiler-anchor, empirical-decision, sql-python-parity, test-fragility]
category: feature
---

# Anime score over the main story only (Main + AlternativeVersion)

**Date:** 2026-07-19 | **Branch:** v0.14.14-scrape-api-migration (part of the post-MAL-migration relations work)

## Summary

An anime's MAL "quality score" — the displayed `avg_score`/`avg_scored_by`, the "Top N%" pill (`score_top_percent`), the default search ordering, and the score/votes HAVING filters — is now computed over the anime's **main story only** (`relation_type ∈ {Main, AlternativeVersion}`, the same anchor set the spoiler frontier uses), not over all its media. Side stories and recaps (`Summary`) are excluded.

Mechanism: a single `RELATION_SCORE_WEIGHTS` map (`app/models/media.py`) drives a relation-weighted mean `S_w = Σ(w·score)/Σ(w)`, `V_w = Σ(w·votes)/Σ(w)`, fed into the unchanged `weighted_score_expr` (`S_w · log10(V_w + 1)`). It ships `{Main:1, AlternativeVersion:1, SideStory:0, Summary:0}` — behaviourally a filter — but the weighted-mean engine means a future non-zero side weight is a one-line change. `S_w`/`V_w` are what's displayed AND what's ranked, so the number, the pill, and the ordering can't drift ("higher in both → higher rank" holds by construction). Media-level scoring (`MediaDAO.score_top_percent`, media search order) is per-row and untouched.

## Why (the empirical study)

Restored the latest prod backup (913 anime / 3794 media) into a throwaway `pgvector/pgvector:pg17` container (the prod image) and measured. The decision was made from the data, not intuition.

**All-media averaging grossly misrepresents flagship anime** — recaps/side stories drag the number down:

| Anime | all media | Main+Alt | Δ |
|---|---|---|---|
| Odd Taxi | 6.97 | 8.63 | +1.66 |
| Monster | 7.37 | 8.89 | +1.52 |
| Vinland Saga | 7.30 | 8.80 | +1.50 |
| Madoka Magica | 7.30 | 8.45 | +1.15 |
| Tensei Slime | 7.37 | 8.12 | +0.75 |

194 anime shift >0.3 pts, 411 move >50 rank positions; the largest *downward* move in the whole catalog is only −0.43. The main-only number also matches MAL's own headline figure (Vinland shows 8.80, not 7.30), where all-media matched nothing.

## Key decisions

- **Main-only, not a continuous side-story weight.** Filter vs SideStory=0.1 → Spearman 0.997 (only 12 anime move >50 positions); =0.25 → 0.991. The knob buys almost nothing measurable, because high-vote side stories sit within ±0.5 of the main average. And a weight can't distinguish a *misclassified* main (Saiki S2, labelled `SideStory`, 707k votes, 8.41) from a minor OVA — that's the classifier's / split-detector's job. Shipped `{1,1,0,0}`.

- **Recaps (`Summary`) → weight 0, for redundancy, not obscurity.** 209 summaries carry scores; 13 have >50k votes (Madoka recap 109k, Death Note 101k, Tensei 78k) — so "nobody rates them" is false. But a recap is a redundant re-telling that mostly scores *below* the main it recaps (Tensei recap 6.79 vs main ~8.1; SAO 6.72). Including them adds no new quality signal and only drags toward a lower number. Redundancy is the reason, not vote count.

- **`SideStory` Movies excluded too — investigated because "movies feel important."** Prod data: side-story movies **drag the main avg at every vote tier** (≥100k votes: 30 drag / 16 lift, avg −0.24; 20–100k: −0.26; <5k: −0.68). The 495 side-story movies have a **median of just 2,985 votes** — the "important movie" feeling is a selection effect from a handful of blockbusters. Even Tensei Slime's Scarlet Bond (7.63) sits −0.49 below its 8.12 main. The reason exclusion is safe: **canonical films are already `Main`** — 190 Main-classified Movies (avg 7.63, *higher* than Main TV's 7.36), including Kimetsu Mugen Train (8.53/1.19M), Kimi no Na wa (8.82), JJK 0, the Eva films, routed there by MAL's `sequel`/`prequel` edges. What stays `SideStory` Movie is what MAL itself labels tangential (gaiden/filler/recap films). So the "important movie" split is done by *classification*, one layer up — better than a `media_type` weight, which would re-admit the draggers to catch films already counted.

- **Display and ranking must share one input, or they look inconsistent.** The consistency invariant the whole design protects: the pill must be a monotonic function of exactly the two numbers shown. So `avg_score`/`avg_scored_by` ARE `S_w`/`V_w` — the same values the ranking and HAVING filters use. Scoping only the ranking (leaving the plain-mean display) would have broken "higher in both → higher Top%", the exact confusion we set out to avoid.

- **Weighted-mean *engine*, shipped degenerate.** `{1,1,0,0}` is behaviourally a filter, but implemented as `Σ(w·x)/Σ(w)` so the weight map is the single knob. The data says a side weight won't be needed; the engine costs little and keeps that a one-liner rather than a re-architecture.

- **Edge case → unscored, no fallback.** Only 2 of 913 anime have a scored side story but an unscored (unaired) main (Fei Ren Zai, Shi Wangzhe A? — donghua). They now read as unscored (no pill), which is truthful — the main story isn't rated yet. A whole-catalog fallback-to-all-media branch wasn't worth 2 rows.

- **Scope is the score only.** `total_episodes`/`total_watch_time`/`media_count`/genre-majority/age/airing stay over ALL media — an anime's episode count or genres shouldn't shrink to its main season.

## Gotchas & learnings

- **The weighted mean returns `double precision`; `log(10, x)` needs `numeric`.** The old `avg()` returned `numeric`, so `weighted_score_expr`'s two-arg `log(10, scored_by+1)` worked. `Σ(case…)/nullif(…)` produces `double precision`, and Postgres has no `log(numeric, double precision)` — restore ran into `function log(integer, double precision) does not exist`. Fix: `cast(…, Numeric)` inside the weighted-mean helper so it matches the old type. The single-arg `log(double precision)` exists but is base-10-by-default — deliberately avoided (the codebase locks the explicit two-arg form to the Python `math.log10` twin via `test_weighted_score_matches_python_twin`).

- **Display twin ≠ ranking twin — a passing display test doesn't prove the SQL.** The displayed avg comes from the *Python* `_compute_anime_aggregates` (phase B); the ranking/HAVING comes from the *SQL* `weighted_mean_*_expr` (phase A). `test_search_anime_aggregated_fields` (display) passed while the SQL was still broken — the SQL only surfaced in a *filter* test. Both twins read the same `RELATION_SCORE_WEIGHTS`, but they must be verified on their own paths. Guarded now by `test_weighted_mean_matches_python_twin`, which runs one dataset (Main + Alt + SideStory + Summary + an unscored member) through *both* and asserts equality — the same dedicated-parity-test convention the scalar `weighted_score_expr`/`_weighted_score` pair uses.

- **Limit-50 search tests are fragile against a populated dev DB — use extreme sentinel values.** `pytest` runs against `DATABASE_URL` with per-test rollback, not a fresh schema; CI's DB is empty, but a real dev catalog isn't. A no-query score-range test relies on the fixture anime clearing the `limit=50` window — and *this very change* raised every real anime's weighted score (removing side-story drag), lifting the top-50 threshold enough to push the weak fixture anime out. Fix per the repo's existing convention (cf. negative-id sentinels): give the fixture's main media an extreme `scored_by` (100M) so its weighted score always tops the window, while keeping `score` inside the tested range. The test's *intent* (does the score filter match?) is preserved; its *determinism against a populated DB* is restored.

## Verification

- SQL spot-checked against the restored prod catalog: Vinland Saga 8.81, Tensei Slime 8.12, One Punch Man 6.92 — matching the analysis.
- `pytest` scoring/search/filter suites green on the populated dev DB (71 tests); `ruff` clean.

## Future work / technical debt

- If a side weight is ever wanted, it's one edit to `RELATION_SCORE_WEIGHTS` — but the data says it changes ranking by <1% (Spearman >0.99) and can't fix misclassification; prefer the classifier/split-detector for "this side story is really a main".
- `score_top_percent` is still a per-request full scan (fine at ~1.4k media); the v0.14.11 note's sweep-time precompute is the lever at 10k+.
