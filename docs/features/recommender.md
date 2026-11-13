# Recommender

A per-user ranking of every anime the user could start next, each with the reason it is
there. The ranking reads the user's own history and watchlist
and compares anime on the [galaxy map](galaxy.md)'s distance.

**Code**: `services/recommender_compute.py` (the numerics, app-free) ←
`services/recommender_service.py` (`load_inputs`) ← `daos/recommendation_dao.py` (the
catalogue as the map sees it, and the franchise signals readiness reads),
`RatingDAO.history`, `WatchlistDAO.priorities`. Nothing serves the ranking yet.

## The natural history

The order a user watched in is evidence only where it is real. Most users start by rating
their whole past in a few sittings, so those days carry no order.

**An event is a media finished**: its first watch event when completed (an on_hold →
completed edit counts when it was finished), else when it was rated. One anime's media on
one day are one event.

**A day is implausible** when at least `IMPORT_MIN_ANIME` anime were first rated on it and
their watch time exceeds `WATCH_HOURS_PER_DAY` per day since the previous rating day. Time
away earns watch time, so a catch-up after a holiday stays natural, while an import —
hundreds of hours in a day — does not.

**The natural history starts after the import.** The import is an implausible day within
`IMPORT_GAP_DAYS` of the first rating, plus every further implausible day less than that gap
after the previous one. Without one, the history starts at the first rating. A later
implausible day is left out of the order as well. Every rated anime still counts for taste,
import or not.

A slow import, a few anime a day, is indistinguishable from watching. An explicit start date
(`ledger`'s `override`) replaces the detected one.

## Candidates

An anime is a candidate when it has an aired main-story media and is one of:

- untouched, or started with an aired main-story media not completed and none dropped — the
  rated states `none`, `in_progress` and `on_hold` ([ratings](ratings.md#rated-state-and-coverage)),
  a paused season counting as story left. `state` reaches this through the media, and a test
  pins it to `_rated_state`;
- listed with an aired media, whatever its state: the list is explicit intent, a planned
  rewatch included.

Finished, unlisted anime are not ranked: complete rewatches are too hard to predict yet.

**Readiness gates them.** A candidate takes the [readiness](readiness.md) verdict: over what
the user listed of it, on every list, or, unlisted, over its whole main story as though it were
listed — so an airing season or one due next season makes it hot. A `waiting` anime — nothing
to watch until a sequel lands — is never a candidate. A `hot` one is left out when the ranking
is asked to (`hot=False`): ratings land at the finale, so a weekly watcher and a finale-week
binge look the same in the data, and only the user can say which they are.

## What a pick commits to

Users plan watch time per franchise, so a candidate's length is everything picking it would
start:

- **listed**: the listed aired media, earlier seasons listed for a rewatch included;
- **unlisted**: the aired main-story media not completed.

Walking those media in `chronological_media_key` order, a
[standalone](readiness.md#the-standalone-rule) media is a commitment of its own. When it comes
first it stands alone, and later it ends the sum.

## The ranking

A **pooled conditional logit**: each candidate's score is one weight vector times its
features, standardised within the moment's candidates, and the weights are shared by every
user. Per-user behaviour enters through the user's own history and propensities, not through
per-user weights.

The families (`NAMES`), each read from the history before the moment ranked:

- **recent picks**: galaxy similarity to the last picks and a decayed mean over more of them,
  plus matches on sector, region, studio, genres, length and release age with the last
  `LAGS`. Continuing a pick counts as the closest thing to it;
- **taste and popularity**: closeness to the user's own top-rated anime, a kNN estimate of
  their own score, MAL score and votes;
- **continuation**: whether it continues a started anime, how the user rated it so far, and
  how long ago they last watched it;
- **freshness**: the user's recency-weighted preference for the candidate's release-age
  bucket (`F8`) and for how long ago its finale aired (`F10`, `FINALE_EDGES`). People binge at
  and after a finale, so a show still airing sits in a bucket of its own;
- **commitment size**: the candidate's length, and the user's preference for its length bucket;
- **the watchlist**: priority, how long ago the entry was listed or last changed, and how
  much watching the list holds.

Due-ness, trends and watch intensity are computed only on request (`harness`), for measuring
rather than ranking.

**The final score adds an enjoyment tilt**, `ALPHA` times the kNN estimate.

**`WEIGHTS` are a stand-in**: the bake-off's reference fit. A family absent from it scores
zero until a fit on the shipped families replaces it.

## The row

The order walks the scores in windows of `ROW`:

- **Caps** hold each window to the user's own share of listed anime and of continuations
  among their natural picks, pulled toward the pooled shares by `CAP_PRIOR` pseudo-picks while
  their history is short (`caps`). Which picks were listed is unknown until the watchlist's
  history records it, so the listed share is the pooled one until then. A list is the strongest single signal, so uncapped it
  would fill the row with the anime the user is likeliest to start anyway.
- **`EXPLORE_SLOTS`** go to new territory: the best-rated candidates from the regions the user
  has covered least. Exploration predicts nothing, so it takes slots rather than competing
  in the score.
- **At most `REGION_CAP` per galaxy region** in a window.

A user with no ratings gets the catalogue's popular picks around the explore slots.

**Each pick names its reason**: the feature group contributing most to its score — continue,
watchlist, fresh, recent, favourite or popular — or `explore` for a slot. A recent or
favourite reason also names the anime it is nearest.

---

**Why it is this way**
- [Recommender](../../compound-docs/2026-11-12-v0.16.6-recommender.md): the measurements
  behind every family, the bake-off, the watchlist rebuilt from the backups, and the
  approaches that lost
