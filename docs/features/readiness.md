# Readiness

What "can I start this anime tonight?" means, and where the answer is computed. The
watchlist is its only surface today — its **Status** filter and the badges beside it —
but the verdict is a property of an anime plus a user, not of that page, so it is
written down here rather than with the page. What the watchlist itself does with
entries, lists and priorities is in
[USER_FLOWS.md](../../phsar/frontend/USER_FLOWS.md) §9.

## The problem

A watchlist mixes two different things: entries you can start now, and entries parked
for the future. Two situations make an entry unstartable, and neither is visible from
the entry itself:

- **Something is airing or about to.** Starting a franchise whose newest season airs
  now, or premieres next season, means catching up and then waiting — the break the
  user wanted to avoid by watchlisting it whole.
- **There is nothing new left.** Everything listed is watched and the rest has not
  aired. You would rewatch when the sequel actually lands, not now.

## Two layers

| Layer | Depends on | Lives in |
|---|---|---|
| A media's **temporal class** | the catalogue alone — `airing_status`, `anime_season_*` | derived at read time from columns the sweeps refresh |
| An anime's **verdict** | those classes, which media the user watchlisted, and their ratings | `utils/watchlistReady`, per request |

The verdict is per-user and no table can hold it: two users with the same anime get
different answers, because it reads their own selection and ratings. The class needs
no table either — it is a `CASE` over columns [jobs](jobs.md)'s `update_sweep` already
keeps current, so it is correct the instant they are.

## The media classes

| Class | Condition | Playable | Blocks |
|---|---|---|---|
| **aired** | `airing_status = 'Finished Airing'` | ✅ | no |
| **airing** | `airing_status = 'Currently Airing'` | partly | **yes** |
| **soon** | not yet aired, season at or before next season | no | **yes** |
| **later** | not yet aired, season beyond next | no | no |
| **tba** | not yet aired, no announced season | no | no |

**Derived from the season, never from `aired_from`.** MAL often gives only a year for an
unannounced title, which `parse_mal_date` pads to January 1st, so a padded date claims a
day-precision premiere it does not have. The season comes from MAL's own `start_season`,
is authoritative where the two disagree, and is present in exactly the same rows as the
date, so consulting the date buys no coverage.

**At or before next season, not exactly next.** A title still marked unaired whose
season has already started is a scrape that has not caught up; treating it as imminent
is the safe read.

**Only main-story media can block** — an upcoming OVA, movie or recap is not a season
you wait for. Two hand-kept twins carry the set: `MAIN_RELATIONS` on the client and
`MAIN_STORY_RELATIONS` in the backend, which filters the franchise columns. It is the
same set the spoiler frontier anchors on, see [spoilers](spoilers.md).

This carries further than it first looks, because the classifier files a franchise's
separate continuities as side stories too (see [relations](relations.md)). An
anthology — Digimon, Gundam, Precure — can have a new series airing while the entry
you listed stays plainly ready, since the airing series continues a different story
and there is nothing to wait for.

## The verdict

Let **W** be the user's watchlisted media for one anime, **F** the anime's whole main
story — including media they never listed.

**A — is there something to watch?**

W is waiting on nothing unaired (so everything listed is available, first watch or
rewatch), **or** some finished entry is still unwatched. A list of nothing but
already-watched seasons plus an announced sequel fails this: no new content, and the
rewatch happens when the sequel lands.

A rated entry still counts as content. A finished media you have already rated and
deliberately kept on the list is a **rewatch**, and a rewatch is watchable.

**B1 — nothing in W is airing or imminent.**

No exemption. Listing a season means you want it, so you would hit the wait; a
`dropped` rating does not release it, and the escape hatch is to unlist it.

**B2 — nothing in F is airing or imminent.**

An unlisted sequel airing now still means catching up and then waiting. Two
exemptions:

- **Media the user dropped.** If they bailed on the season that is airing, they are
  not waiting for it. This applies only to airing media in practice — a not-yet-aired
  media can never carry a rating (`CannotRateUnairedError`).
- **The standalone rule**, below.

An anime is **ready** when all three hold.

## The standalone rule

A single watchlisted media long enough to be its own commitment releases B2, so
ongoing franchise content the user did not list stops blocking it — Dragon Ball
without Super, Naruto without Boruto, Gintama.

**`STANDALONE_SECONDS` is 20 hours, per media and never summed.** The line sits at the
classic 4-cour (~50 episode) format, where a series that stands on its own begins. It is
calibrated against the catalogue, so re-measure before moving it.

Summing is the tempting mistake, and the reason the rule takes the maximum: franchises
exist that are one continuous story told in short seasons, whose total clears any sane
threshold while no single season comes close. Summed, they read as standalone and a new
airing season gets hidden, which is exactly wrong.

Two limits worth knowing:

- An open-ended show has no episode count, so `total_watch_time` is null and it never
  clears the threshold. Harmless — it is airing, so it is blocked anyway.
- An anime here is the **whole franchise**, so B2 is aggressive on the large ones: any
  new entry blocks every selection, and this exemption is what rescues them.

## What the two grains show

**Anime grain** — one card per anime, filtered on the verdict, each carrying at most one
badge. The verdicts are `ready`, `standalone`, `hot` and `waiting`; what each says to the
user is in USER_FLOWS §9.2.1.

**Media grain** — gated on the same verdict, so both views agree on which franchises
qualify. A **ready** anime then narrows to the entries that can actually be played: a
rewatch stays visible, an announced season does not. A **hot** or **waiting** anime
keeps all of its entries, because there the question is *why*, and the airing or
unaired entry is the answer.

**The filter chips are a union, like the list and priority ones.** `standalone` rides
under Ready rather than taking a chip of its own; `CHIP_OF` in `watchlistReady` is where
that mapping lives.

**The list and priority chips never change a verdict.** It is computed over the
unfiltered entry set — `statusByAnime` argues why.

## Where it is computed

The rules are client-side, and live in `utils/watchlistReady` because the watchlist is
the only surface so far: `/watchlist/items` already returns the user's whole watchlist in
one fetch, and both grains are derived from it in the browser. A second surface wanting
the same verdict is the point to revisit that — the compound doc argues why it is not
already a server-side column. The backend supplies only the inputs the client cannot
derive:

| Input | Source |
|---|---|
| `airing_status`, `anime_season_*`, `relation_type`, `total_watch_time` | the media row |
| `watch_status` | `LEFT JOIN ratings` scoped to the caller |
| `franchise_airing`, `franchise_upcoming_key` | `WatchlistDAO._franchise_signals` |

The franchise pair is the only part of the projection that reads media **outside** the
user's watchlist, which is what makes B2 possible — no entry row can carry the status
of a sequel that was never listed.

`franchise_upcoming_key` is the franchise's earliest announced season as a sortable
`year * 10 + rank` integer. The client builds the same key for next season and
compares, which keeps the moving boundary in one place instead of pushing a cutoff
into SQL. No import spans Python and TypeScript, so the encoding is held together only
by a test on each side pinning the same season to the same number.

---

**Why it is this way**
- [Quality-of-life upgrades](../../compound-docs/2026-08-29-v0.15.5-quality-of-life.md) — the season-over-date choice, the per-media threshold and the catalogue shapes behind it, and the case table A/B1/B2 came from
- [Watchlist](../../compound-docs/2026-07-23-v0.15.0-watchlist.md) — one list per entry, and why storage is media-grain while the default view is not
