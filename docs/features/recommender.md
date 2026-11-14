# Recommender

A per-user ranking of every anime the user could start next, each with the reason it is
there. The ranking reads the user's own history and watchlist
and compares anime on the [galaxy map](galaxy.md)'s distance.

**Code**: `services/recommender_compute.py` (the numerics, app-free) ←
`services/recommender_service.py` (its inputs, and the stored ranking's refresh) ←
`daos/recommendation_dao.py`
(the catalogue as the map sees it, the franchise signals readiness reads, the stored ranking
and the watchlist's log), `RatingDAO.history`. `models/recommendation.py` and
`models/watchlist_event.py` hold what is stored; `services/recommender_eval.py` fits and
measures it. Search serves it.

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

A slow import, a few anime a day, is indistinguishable from watching. An explicit start date,
the user's `history_start` setting, replaces the detected one; `GET /ratings/history-start`
returns both.

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
the user listed of it, on every list, once some of that has aired; otherwise over its whole
main story as though it were listed — so an airing season or one due next season makes it hot.
A list holding only an unannounced sequel commits to nothing yet, so the season the user has
left can read ready here where the watchlist reads Waiting. A `waiting` anime — nothing to
watch until a sequel lands — is never a candidate, nor is a `hot` one with nothing to start
now: its rewatch belongs to when the sequel lands, though the watchlist shows it Hot. Any other
`hot` one is left out when the user turns `recommend_hot` off: ratings land at the finale,
so a weekly watcher and a finale-week binge look the same in the data, and only the user can
say which they are.

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
user. The watchlist's features stay raw: a list holds a handful of the candidates, and a
column that sparse standardises to values that swamp every other feature. Per-user behaviour
enters through the user's own history and propensities, not through per-user weights.

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

**The list is known from the ledger's `listed_from` on** — the [log](#the-watchlists-history)'s
start — and reads as empty before it. Today's list replayed at a past moment holds only what
was not picked since, so it would teach the model that listed means not picked.

Due-ness, trends and watch intensity are computed only on request (`harness`), for measuring
rather than ranking. So are the features of the ranked families that `WEIGHTS` leaves out:
none adds signal of its own once the rest are in, and without them the weights hold steadier
from one fit to the next.

**The final score adds an enjoyment tilt**, `ALPHA` times the kNN estimate.

**`WEIGHTS` are a reviewed fit**: the harness's pooled fit over every user's natural picks
(below), committed as constants and refit as the data grows.

## The row

The order walks the scores in windows of `ROW`:

- **Caps** hold each window to the user's own share of listed anime and of continuations
  among their natural picks, pulled toward the pooled shares by `CAP_PRIOR` pseudo-picks while
  their history is short (`caps`). A pick was listed when its anime was on the list at that
  moment, which is known only from `listed_from` on. A list is the strongest single signal,
  so uncapped it would fill the row with the anime the user is likeliest to start anyway.
- **`EXPLORE_SLOTS`** go to new territory: the best-rated candidates from the regions the user
  has covered least, weighed by the user's own preference for their length, so a long run
  sinks for someone who rarely picks one. Exploration predicts nothing, so it takes slots
  rather than competing in the score.
- **At most `REGION_CAP` per galaxy region** in a window.

A user with no ratings gets the catalogue's popular picks around the explore slots.

**Each pick names its reason**: `continue` for a continuation, listed or not, else the feature
group contributing most to its score — watchlist, fresh, recent, favourite or popular — or
`explore` for a slot. A recent or
favourite reason also names the anime it is nearest.

## The watchlist's history

`watchlist_events` records every entry added, changed (its priority or list) or removed: the
entry's state after the event, and for a removal the state it removed. A row trigger on
`watchlist` writes it, defined in the migration that created the table, so no write path can
skip it; the ledger turns it into the listing stretches the features read
(`listings_from_log`).

**It merges churn.** A write within three days of the entry's last event folds into that
event — dated at the write, as the change from the state before it — or deletes it when the
entry is back where it was. A toggle or a priority changed and changed back leaves nothing, and
churn leaves at most one row per entry. A rating or watch of the media anywhere in the span
the merge would rewrite, or within three hours before it, keeps every event: a watch and the
removal it caused belong together. A relisting after the window is an event of its own.

**The log is whole only from `listed_from`**, its first rows' `created_at`: it starts from the
entries listed then, each as found, so one listed and removed earlier is absent.

## Serving

Each user's ranking is stored whole (`recommendations`) beside the key of everything it was
computed from (`recommendation_state`): the user's ratings' and log events' count, latest change
and the sum of their media's anime ids (a merge or split moves media between anime without
touching those rows), the map's stars — a refit replaces every one — the recommender settings,
`recommender_compute.version()` and the UTC date. A note edit touches none of them.

**It recomputes on read.** A search that reads the ranking — the `for_you` sort or the
`recommended` filter ([search](search.md#personal-filters-and-sort)) — compares the key first;
when it changed, it takes a lock on the user's state row, checks again, computes in a thread,
replaces the rows and commits. A second request arriving meanwhile waits on the lock and finds
the ranking fresh.

**The row's exposure is logged as stretches** (`recommendation_exposure`): an anime entering
the top `ROW` opens one, staying there extends it — its `modified_at` and best rank — and
leaving it ends it by not being extended. A recompute that changes nothing in the top writes
no row, so the log grows with turnover, not with reads, and keeps what was shown and not
picked beside what was.

## Measuring it

`recommender_eval` replays every user's natural history: each pick after the first `LAGS` is a
decision among the candidates of its moment, with the features `decide` gives them then. A
pick that was no candidate then — a side story alone — has nothing to rank.

- **The fit** is the conditional logit over each decision's full candidate set, L2 `LAMBDA`,
  on the features `WEIGHTS` ranks.
- **The splits**: the time split tests each user's latest decisions on a fit to their earlier
  ones and everyone else's; leave-one-user-out tests each user on a fit to the others. Each
  reports the pick's rank under the logit alone, under the ranking's score and in the row —
  median and hit@`ROW`, also over the picks the user rated at or above their median — and the
  held-out NLL, for given weights and a fresh fit — and on the logit alone for the similarity
  baseline.
- **Ablations**: what each family adds, the shipped set fitted with and without it, with a
  paired sign-flip p on the NLL. The harness-only families and the unranked features are
  measured as additions, and `W_backlog` alone as well: it ships only while removing it raises
  the held-out NLL in every split.
- **Per-user weights**, pulled toward the pooled ones, on the time split.
- **The watchlist**: from `listed_from` on, the share of picks listed at the time, their lift
  by priority, entry age and list over what choosing at random among the candidates gives,
  and the conversion hazard per listed-anime-day. Each figure carries its n: they arrive thin
  and firm up as the history grows.

`scripts/backtest_recommender.py` prints the report, and can rebuild the watchlist's past from
the backups, back before the log began.

---

**Why it is this way**
- [Recommender](../../compound-docs/2026-11-12-v0.16.6-recommender.md): the measurements
  behind every family, the bake-off, the watchlist rebuilt from the backups, the first fit,
  and the approaches that lost
