# Spoiler protection

Hides or blurs media a user hasn't reached yet in a franchise, without hiding the
franchise itself.

**Code**: `services/spoiler_service.py` (frontier + cache) →
`models/user_visible_media.py` (the cache) → `SpoilerGuard.svelte` (rendering).

## Levels

A per-user setting with three values: `off`, `blur`, `hide`.

**Anime covers and descriptions are never spoiler-protected** — only media within
an anime are. Hiding the franchise you searched for would defeat the search.

## The frontier

Per anime, all media up to **and including** the next unwatched *anchor* entry are
visible. Outside that sentence: an individually rated media stays visible even
beyond the frontier (you have already watched it); an anime with no anchors at all
shows only its first media; and once every anchor is rated the whole anime is
visible.

An anchor is a media whose relation type is `Main` **or** `AlternativeVersion`.
Retellings extend the story, so each alt-version gates the next: rating the
Evangelion TV series reveals Rebuild Movie 1, but not Movies 2–4.

The backend walk orders media with `filter_service.chronological_media_key`, the
same key the anime-detail table and the related-media carousel use — so the order
a user sees matches the order the frontier walks. Diverging keys would be a silent
bug where the visible set doesn't match the displayed sequence.

The client-side walk in `utils/spoilerFrontier.ts` is the one deliberate
divergence: it tiebreaks same-season media on `uuid` where the backend uses
`mal_id`, because the client has no `mal_id` to hand. Two media in the same season
can therefore order differently there than in the table beside them.

## The cache

Results are precomputed into `user_visible_media`, keyed by media id. `hide` mode
in media search is then just `WHERE media.id IN (…)`.

Three recompute paths:

| Trigger | Scope |
|---|---|
| Rating change | that (user, anime) |
| Registration, startup backfill | that user, whole catalogue |
| Catalogue mutation — save, sweep, merge, split | the changed anime, across all non-restricted users |

The third is scoped rather than whole-catalogue. The frontier is per-anime and the
cache keys on media id, and media ids only move *between the named anime* on merge
or split — so scoping is sufficient, and the cost is O(users × changed) rather than
O(users × everything). Each call site passes the set it already tracks: save passes
its new anime, the sweep its probe-attached anime, merge the survivor, split the
source plus the new rows.

The anime detail page computes the frontier locally rather than reading the cache,
so it reflects a rating made moments ago. The media detail page reads the cached
set instead, and covers the same window with an optimistic "rated ⇒ visible" check
plus a refetch.

The startup `backfill_spoiler_visibility` only covers users with **zero** cache rows
(new deployments, pre-feature users). It does not repair partial drift on existing
users — that's what the scoped recomputes are for.

## Restricted users

Guests are pinned to `spoiler_level=off` and excluded from the cache entirely: they
cannot rate, so they have no frontier.

The pin has two altitudes, because one isn't enough:

- `user_settings_service.update_settings` guards the **write** path, dropping
  `spoiler_level` for a restricted user.
- A startup seeder repairs **data at rest** — resetting any legacy non-`off` level
  and deleting stale cache rows.

The second exists because a user demoted to `restricted_user` by a direct database
edit while holding `hide` would otherwise read an empty cache and see a blank
catalogue, and a write-path guard cannot fix rows that predate it.

The settings UI renders their rating-related controls **disabled rather than
hidden**, so the capability is discoverable.

## Watchlist does not interact

Watchlist writes never touch the frontier. An entry is "want to watch", not
"watched" — the two are independent by design.

---

**Why it is this way**
- [Content pipeline](../../compound-docs/2026-05-09-v0.14.0-content-pipeline.md) — the frontier algorithm and cache
- [Little fixes](../../compound-docs/2026-06-17-v0.14.7-little-fixes.md) — scoping the recompute to changed anime
- [Watchlist](../../compound-docs/2026-07-23-v0.15.0-watchlist.md) — why watchlist stays out of it
