# Watchlist

What a user wants to watch: one entry per media, filed on one list with a priority and
an optional note. The `/watchlist` page, the bookmark on every card and hero, and the
bulk dialogs on the anime page all read and write it. What each screen does is in
[USER_FLOWS.md](../../phsar/frontend/USER_FLOWS.md) — §9 for the page, §6 for the anime
page; this doc is the mechanism under them.

**Code**: `services/watchlist_service.py` (entries) + `services/tag_service.py` (lists)
→ `daos/watchlist_dao.py` + `daos/tag_dao.py` → `models/watchlist.py`, `models/tag.py`.

## An entry is per media

`Watchlist` carries `(user_id, media_id)` under `unique_user_media_watchlist`, one
required `tag_id`, a `priority` from 1 (high) to 3 (low) and an optional note. As with
[ratings](ratings.md), "watchlist the whole anime" is a bulk write of one row per media,
so one anime can span several lists — its bookmark renders each distinct list's colour,
as a gradient when there is more than one.

## A list is a tag

"List" is the UI term; the table is `tag`, and each entry has exactly one.

- **The default list is immutable.** Every non-restricted user has one
  `DEFAULT_TAG_NAME` list in a reserved colour kept out of the user palette, so a
  custom list cannot impersonate it. Renaming, recolouring or deleting it raises
  `DefaultTagImmutableError` — so the UI always has a list to preselect, and a delete
  always has somewhere to reassign to. `create_default_tag` is idempotent and leaves
  the commit to its caller (registration, the seeder, delete-with-reassign).
- **Deleting a list reassigns or deletes its entries.** `delete_tag(reassign_entries=)`
  moves them to the default list first or deletes them — either way it returns the
  count for the confirm copy. `empty_tag` clears a list but keeps it — the only bulk
  clear the default list has.
- **Names are unique per user, at three layers**: the `unique_user_tag` constraint is
  the truth, a service pre-check gives the friendly error, and an `IntegrityError`
  backstop closes the check-then-write race a double click opens.
  `TAGS_PER_USER_LIMIT` is an anti-runaway ceiling, not a target — the page's list
  filter is multi-select, so extra lists are cheap.

## Bulk writes and the note target

`bulk_upsert_watchlist` applies one list and one priority to every media in the
request, and puts the note on **one** of them: the chronologically-first main media of
the request, by `filter_service.select_note_target_index(media_list, latest=False)`.
It mirrors bulk rating, which takes the last — a watchlist note says "start here", a
rating note "my take on the latest".

- **Every other entry keeps its note.** A bulk write is also how a whole anime changes
  list or priority, so clearing there would destroy notes the request never mentioned.
- **An omitted `note` is not a null one.** `"note" in data.model_fields_set` separates
  them: omitted leaves every note alone, null clears the target's. That is what lets a
  client move an anime without knowing which entry holds its note.

### The update form reads the target, never derives it

`BulkWatchlistDialog` shows the note it is about to edit, so it needs the target. It
reads it from `GET /watchlist/anime/{uuid}?media_uuids=…` — the anime's entries plus
`note_target_media_uuid`. Two rules hold that together, and each one broken is the same
failure: the box shows one entry's note and the save writes it over another's, one note
in, one out, nothing logged.

- **The client never re-derives the rule**, however safe a mirror over the same sort
  key looks.
- **The target is picked over the selection the save will send**, not over the anime's
  listed entries. The two differ whenever the form edits part of an anime.

The client's half — when it sends `note` at all, and what a failed prefill blocks — is
argued in the component.

## The reads whose shape is a decision

Every endpoint the client calls is listed in
[USER_FLOWS.md](../../phsar/frontend/USER_FLOWS.md) §13; these are the ones built to a
shape on purpose.

- **`/watchlist/media-tags` feeds the `watchlistTags` store**, which refreshes eagerly
  after every watchlist write, unlike the lazy rating caches —
  `stores/ratingCoverage.ts` says why the two differ.
- **`/watchlist/items` is a flat projection**, built the way
  [ratings.md](ratings.md)'s scores projection is. It ships the `Media.total_watch_time`
  hybrid rather than episodes and duration, so the client does no runtime arithmetic.
- **Readiness inputs travel with the entries**: [readiness.md](readiness.md).

## Coupling to other subsystems

- **Spoilers** — none, by design: [spoilers.md](spoilers.md).
- **Ratings** — independent; the only link is the inline remove a rating offers on a
  listed media ([USER_FLOWS.md](../../phsar/frontend/USER_FLOWS.md) §7.4).
- **Readiness** — reads the entries and the user's ratings: [readiness.md](readiness.md).
- **Curation** — a media delete cascades to its entries: [curation.md](curation.md).
- **Search** — `watchlisted` filters by the entries: [search.md](search.md#personal-filters-and-sort).

---

**Why it is this way**
- [Watchlist](../../compound-docs/2026-07-23-v0.15.0-watchlist.md) — one list per entry, and staying out of the spoiler frontier
- [Ratings ↔ watchlist coupling](../../compound-docs/2026-07-26-v0.15.1-ratings-watchlist-coupling.md) — why the two stay independent
- [Quality-of-life upgrades](../../compound-docs/2026-08-29-v0.15.5-quality-of-life.md) — readiness and watchtime
- [Tests, CI, typing, rated coverage](../../compound-docs/2026-09-19-v0.15.6-test-and-ci-setup.md) — the whole-anime update form, and why its note target is picked over the selection
