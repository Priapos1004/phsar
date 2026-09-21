# Ratings

What a user records about something they watched: a score, a watch status, a
free-text note, and the optional attribute scales on `RatingAttributes`.
Everything the `/ratings` page, the rating card and the spoiler frontier read
starts here.

**Code**: `services/rating_service.py` (writes, guards, projections) →
`daos/rating_dao.py` + `daos/watch_event_dao.py` (the SQL) → `models/ratings.py`,
`models/watch_event.py`, `models/rating_search.py`.

## A rating is per media

There is no anime-level rating table. `Ratings` carries `(user_id, media_id)`
under a `unique_user_media_rating` constraint, and "rate the whole anime" is a
bulk write of one row per media. What the shape buys downstream:

- A `LEFT JOIN Ratings ON (media_id, user_id)` is **0-or-1**, so it can never fan
  a media row set out. Every per-user projection that joins this way depends on
  it, hardest where the joined column feeds an aggregate — the invariant is
  written beside each join.
- Ratings survive merge and split — see [relations.md](relations.md). Only the
  anime a rating rolls up into changes, which is why anything aggregated per
  anime is computed live rather than stored.

## Watch status

A `WatchStatus` enum (`completed` / `on_hold` / `dropped`) on `Ratings`.
`on_hold` is split out from `dropped` so a future "continue watching"
recommendation can resume paused-but-not-abandoned shows; both carry
`episodes_watched`. The search filter (`RatingSearchFilters.watch_status`) is a
list, so the library can filter several statuses at once.

## Guards on a write

`_upsert_single_rating` is the shared core of the single and bulk paths, so both
are guarded identically.

- **Not-yet-aired.** A *fresh* rating on a media that is not `Media.is_rateable`
  raises `CannotRateUnairedError`; an existing rating stays editable so a
  correction isn't trapped once the show airs. The frontend hides those media —
  this backstops a direct or stale call. A bulk write with an unaired member
  aborts the whole batch.
- **Episode clamp.** `episodes_watched` is clamped to `[0, media.episodes]`, or
  to `[0, UNKNOWN_EPISODES_CAP]` when the catalogue has no episode total. A
  server backstop for the client's input clamp, so a direct call can't store
  INT_MAX. This is about the stored value, not the chart — the watch-time stat
  clamps too.
- **Bulk note placement.** `bulk_upsert_ratings` puts the note on the
  chronologically-**last** main media, via the shared
  `filter_service.select_note_target_index(media_list, latest=True)` that bulk
  watchlist calls with `latest=False`. Intrinsic media order, so it is invariant
  to request and click order; an `aired_from` tiebreak falls back to request
  order on same-date ties (two same-season movies, say).
- **Bulk contract — completed, full-run only.** Bulk rating is a whole-anime "I
  finished this" action, so `watch_status` / `episodes_watched` live on
  `RatingCreate` but deliberately **not** on `RatingBase` / `RatingBulkCreate`;
  the bulk path pins every media to `completed` plus `media.episodes`. Keeping
  them off the bulk schema means the endpoint cannot advertise inputs it
  ignores, nor produce a dropped rating claiming the full run.

## Watch events and rewatch

`watched_count` is derived from watch-event rows
(`WatchEventDAO.counts_for_user_media_ids`, one grouped query batched into
`_ratings_to_out`), never stored.

`_maybe_log_first_watch` logs exactly one event when a write lands `completed`
**and** the user has no prior events for that media. So a first completion and
an `on_hold`/`dropped` → `completed` transition each log once, while re-rating
media that already has history never duplicates. `log_rewatch` always appends.

**Delete is an opt-in cascade.** `delete_rating`, `bulk_delete_ratings` and
`upsert_rating` all take `delete_watch_history` (default False): history is kept
so a delete-then-re-add, or a `completed` → `on_hold` downgrade, doesn't strand
or pollute the series. The frontend asks before passing True. Events also clear
via DB `ON DELETE CASCADE` on account or media deletion.

## Rated coverage

`get_rating_coverage` (`GET /ratings/coverage`) answers "how much of this anime
have I rated" for each anime the user has touched, feeding the per-anime
coverage indicator on cards. The answer is a `CoverageTier`:

| Tier | Reached when |
|---|---|
| `all` | every rateable media carries a `completed` rating |
| `main` | every rateable main-story media carries a `completed` rating |
| `some` | any rating exists, whatever its status |

Highest tier wins. `dropped` and `on_hold` are opinions rather than
completions, so they hold an anime at `some`: dropping a side story still
leaves `main` reachable, dropping a main does not. Both completion tiers also
require at least one **rateable** main-story media — the guard, and why it is
needed, are on `_coverage_tier`.

Rateable means `Media.is_rateable`, the same predicate the unaired guard above
refuses on. Anime with no rating are **absent** from the response rather than
reported as untouched; that comes from the query scope, described on
`RatingDAO.get_anime_coverage`.

The media grain has no tier — see [search.md](search.md).

## The scores projection

`get_rating_score_items` is a deliberate **one-query, two-consumer** projection.
`RatingScoreItem` is intentionally wide (cover, MAL score and votes, per-episode
`duration_seconds`, `episodes_watched`, season, `relation_type`, `created_at`,
attributes) so both the RatingCard consistency helper and the whole `/ratings`
page (list + stats) derive from one fetch — there is no per-user stats endpoint.
The criteria for splitting it later are in the `RatingScoreItem` docstring.

Every field being a **scalar** is what lets `RatingDAO.get_all_for_score_items`
serve it as one flat projection, genres and studios via `array_agg` with no ORM
hydration; a field needing a relationship traversal would reintroduce a round
trip per collection. `/watchlist/items` is built the same way, and both share
`media_genre_names()` / `media_studio_names()` in `daos/media_projections.py` so
their array ordering cannot diverge.

Listing routes order newest-first through `base_dao.recency_order` — the
primary-key tiebreak is load-bearing, see
[database.md](../../.claude/rules/database.md).

## Notes are searchable

Notes are embedded for search — see [search.md](search.md). `/search/ratings`
takes the full media filter set plus the rating-specific ones, scoped to the
caller's own ratings.

## Coupling to other subsystems

- **Spoilers** — a rating write moves the frontier: [spoilers.md](spoilers.md).
- **Watchlist** — independent by design; the only link is the inline remove a
  rating offers on a listed media ([USER_FLOWS.md](../../phsar/frontend/USER_FLOWS.md) §8).
- **Readiness** — a rated media still counts as content:
  [readiness.md](readiness.md).

---

**Why it is this way**
- [Ratings backend](../../compound-docs/2026-04-04-v0.9.0-ratings-backend.md) — the original model and its media-level decision
- [Ratings QoL](../../compound-docs/2026-06-22-v0.14.10-ratings-qol.md) — watch status replacing the dropped boolean, and watch events
- [Further QoL](../../compound-docs/2026-06-22-v0.14.11-further-qol.md) — the rating-consistency helper
- [Ratings page](../../compound-docs/2026-06-23-v0.14.12-ratings-page.md) — the one-fetch page and its projection
- [Ratings ↔ watchlist coupling](../../compound-docs/2026-07-26-v0.15.1-ratings-watchlist-coupling.md) — why the two stay independent
