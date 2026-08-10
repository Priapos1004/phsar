# Compound-docs index

**These record why something changed** — the decision, what was tried, what failed.
They are dated and frozen: a claim here was true when written and may since have been
superseded. For how a subsystem works **today**, read `docs/features/` instead.

`/update-docs` owns this index.

## By subsystem

Docs whose filename carries no version are the easiest to miss, so they are listed
first within their subsystem.

**Scraping** — [scraper quirks & field notes](2026-05-11-jikan-scraper-quirks.md) (upstream data oddities; written against **Jikan v4**, so its endpoints, its rate-limit reasoning and the since-removed `Crossover` relation are historical — the data quirks still hold) · [MAL API v2 migration](2026-07-18-v0.14.14-mal-api-migration.md) (endpoint/field mapping, substance-gate waivers, the empty-relation-cache regression)

**Relations** — [classifier redesign](2026-05-16-v0.14.1-search-and-data-fixes.md) (the two-pass design) · [split candidates](2026-05-18-v0.14.2-split-candidates.md) (third pass, TERMINAL edge capture) · [merge-candidate fix](2026-06-11-v0.14.4-merge-candidates-fix.md)

**Search & scoring** — [little fixes](2026-03-31-little-fixes.md) (Argon2 rehash-on-login, `fsk`→`age_rating`, `anime_season` split into enum + year, hentai filtering, search-UX fixes) · [anime score over the main story only](2026-07-19-anime-score-main-only.md) (the prod-data study behind the relation weights) · [anime search & detail pages](2026-04-09-v0.11.0-anime-search-pages.md)

**Jobs & sweeps** — [content pipeline](2026-05-09-v0.14.0-content-pipeline.md) (the original worker and BFS, the duplicate detector, the maintenance-window foundation — the largest single record) · [sweep observability](2026-06-15-v0.14.5-sweep-observability.md) (the audit-diff summary) · [media-level sweep](2026-06-17-v0.14.8-media-level-sweep.md) (anime → media selection) · [little fixes](2026-06-17-v0.14.7-little-fixes.md) (failure logging, not-yet-aired relations, spoiler-cache scoping) · [reliability bug-fixes](2026-07-17-v0.14.13-bug-fixes.md) (the outage circuit breaker, the sliding session, the embedding case-fold)

**Backups & deployment** — [deployment & infrastructure](2026-04-19-v0.13.0-deployment.md) (Coolify, images, the original backup design) · [backup retention refinement](2026-06-16-v0.14.6-backup-refinement.md) (the three pools) · [quality-of-life upgrades](2026-07-27-v0.15.3-quality-of-life.md) (backup revision stamping and the composite `status`; the archival cadence as a **per-row window on the long-tail tier**, not a fifth tier; filter/score scoping)

**Performance** — [performance baseline](2026-08-06-performance-baseline.md) (measured at prod catalogue scale; the reference point for **ratios and buffer counts** — it states that wall-clock is not portable across harnesses) · [efficiency improvements](2026-08-06-v0.15.4-efficiency-improvements.md) (running notes, self-marked as not yet a finished record)

**Ratings & watchlist** — [ratings backend](2026-04-04-v0.9.0-ratings-backend.md) · [media detail + rating UI](2026-04-05-v0.10.0-media-detail-rating-ui.md) · [ratings QoL](2026-06-22-v0.14.10-ratings-qol.md) (watch status, watch events) · [further QoL](2026-06-22-v0.14.11-further-qol.md) (detail-page polish: `score_top_percent`, genre tooltips, the rating-consistency helper) · [ratings page](2026-06-23-v0.14.12-ratings-page.md) · [watchlist](2026-07-23-v0.15.0-watchlist.md) · [ratings ↔ watchlist coupling](2026-07-26-v0.15.1-ratings-watchlist-coupling.md) · [shareable cards](2026-07-26-v0.15.2-shareable-rating-cards.md)

**Spoilers** — [user settings, themes, admin](2026-04-11-v0.12.0-user-settings-profile.md) (where the spoiler frontier, the three levels and the `user_visible_media` cache are designed, alongside the settings and theme system)

**Admin & UI** — [v0.8.0](2026-04-01-v0.8.0.md) (shadcn-svelte migration, Svelte 5 runes, theme system) · [ECharts in SvelteKit + Svelte 5](2026-04-06-echarts-integration.md) (SSR crash on static import, Vite browser conditions, container sizing) · [admin page rework](2026-05-26-v0.14.3-admin-page-rework.md) · [cleanup sweep](2026-06-18-v0.14.9-cleanup-sweep.md) (themed Tooltip migration, curation history, the v6 probe-attach audit)

## Chronological

| Date | Doc |
|---|---|
| 2026-03-31 | [little fixes](2026-03-31-little-fixes.md) |
| 2026-04-01 | [v0.8.0](2026-04-01-v0.8.0.md) |
| 2026-04-04 | [v0.9.0 ratings backend](2026-04-04-v0.9.0-ratings-backend.md) |
| 2026-04-05 | [v0.10.0 media detail + rating UI](2026-04-05-v0.10.0-media-detail-rating-ui.md) |
| 2026-04-06 | [ECharts integration](2026-04-06-echarts-integration.md) |
| 2026-04-09 | [v0.11.0 anime search & detail pages](2026-04-09-v0.11.0-anime-search-pages.md) |
| 2026-04-11 | [v0.12.0 user settings, themes, admin](2026-04-11-v0.12.0-user-settings-profile.md) |
| 2026-04-19 | [v0.13.0 deployment & infrastructure](2026-04-19-v0.13.0-deployment.md) |
| 2026-05-09 | [v0.14.0 content pipeline](2026-05-09-v0.14.0-content-pipeline.md) |
| 2026-05-11 | [scraper quirks & field notes](2026-05-11-jikan-scraper-quirks.md) |
| 2026-05-16 | [v0.14.1 search & data fixes](2026-05-16-v0.14.1-search-and-data-fixes.md) |
| 2026-05-18 | [v0.14.2 split candidates](2026-05-18-v0.14.2-split-candidates.md) |
| 2026-05-26 | [v0.14.3 admin page rework](2026-05-26-v0.14.3-admin-page-rework.md) |
| 2026-06-11 | [v0.14.4 merge-candidates fix](2026-06-11-v0.14.4-merge-candidates-fix.md) |
| 2026-06-15 | [v0.14.5 sweep observability](2026-06-15-v0.14.5-sweep-observability.md) |
| 2026-06-16 | [v0.14.6 backup retention refinement](2026-06-16-v0.14.6-backup-refinement.md) |
| 2026-06-17 | [v0.14.7 little fixes](2026-06-17-v0.14.7-little-fixes.md) |
| 2026-06-17 | [v0.14.8 media-level sweep](2026-06-17-v0.14.8-media-level-sweep.md) |
| 2026-06-18 | [v0.14.9 cleanup sweep](2026-06-18-v0.14.9-cleanup-sweep.md) |
| 2026-06-22 | [v0.14.10 ratings QoL](2026-06-22-v0.14.10-ratings-qol.md) |
| 2026-06-22 | [v0.14.11 further QoL](2026-06-22-v0.14.11-further-qol.md) |
| 2026-06-23 | [v0.14.12 ratings page](2026-06-23-v0.14.12-ratings-page.md) |
| 2026-07-17 | [v0.14.13 reliability bug-fixes](2026-07-17-v0.14.13-bug-fixes.md) |
| 2026-07-18 | [v0.14.14 MAL API v2 migration](2026-07-18-v0.14.14-mal-api-migration.md) |
| 2026-07-19 | [anime score over the main story only](2026-07-19-anime-score-main-only.md) |
| 2026-07-23 | [v0.15.0 watchlist](2026-07-23-v0.15.0-watchlist.md) |
| 2026-07-26 | [v0.15.1 ratings ↔ watchlist coupling](2026-07-26-v0.15.1-ratings-watchlist-coupling.md) |
| 2026-07-26 | [v0.15.2 shareable cards](2026-07-26-v0.15.2-shareable-rating-cards.md) |
| 2026-07-27 | [v0.15.3 quality-of-life upgrades](2026-07-27-v0.15.3-quality-of-life.md) |
| 2026-08-06 | [performance baseline](2026-08-06-performance-baseline.md) |
| 2026-08-06 | [v0.15.4 efficiency improvements](2026-08-06-v0.15.4-efficiency-improvements.md) |
