# Curation — the admin review queues

The admin **Curation** tab's queues — **merge** (two anime rows are the same
franchise), **split** (one anime row holds two franchises) and **delete** (an
entry should leave the catalogue) — share one lifecycle, one dismissed-decisions
surface and one pending-count endpoint.

Detection never acts. Every queue exists because the signal is good enough to
raise but not good enough to apply: a title match can be a coincidence, a
disjoint cluster can be a judgment call, and a 404 can be MAL having a bad
minute. What the detectors produce is a proposal.

How the relation graph produces the merge and split signals is in
[relations](relations.md); this doc owns what happens to a candidate afterwards.

## The shared lifecycle

| Status | Meaning |
|---|---|
| `pending` | a detector raised it; the admin has not decided |
| `dismissed` | reviewed and rejected — the proposal was wrong |
| `merged` / `split` / `deleted` | applied |

**A dismissal is sticky, and the row itself is the mechanism.** Each detector
pre-fetches the identities it has already seen — merge by anime pair, split by
cluster signature, delete by mal_id — *regardless of status*, and skips them
before computing any signal. Without that, the next run re-raises what the admin
just rejected, every night, forever.

The consequence is that un-dismissing means **deleting the decision**, not
flipping it back: once the row is gone the identity leaves the skip-set and the
next detection re-raises it naturally. It accepts only `dismissed` rows — a
`pending` row belongs to the live queue, and an applied one is an audit record.

**Resurfacing is deliberately ungated** beyond admin, unlike the destructive
curation actions: it frees a decision rather than destroying anything, so a
confirmation would have nothing to protect.

Merge is the exception to that table: applying one deletes anime B, whose cascade
([relations](relations.md)) takes the candidate row with it. So there is no
`merged` row to find — the absence is the record.

## The delete queue

The detectors, both in `delete_candidate_service`:

**`sweep_404`** — the update sweep got a 404 refreshing a media, meaning MAL
deleted the entry upstream. Raised per media, during the sweep.

**`low_signal`** — a standalone anime whose only media never gained MAL traction:
no published score, under 50 votes, finished airing, and **premiered over a year
ago**. These are what the seasonal sweep drags in when MAL lists an obscure entry
for a season.

The age floor is what separates "nobody wanted this" from "nobody has seen it
yet". MAL votes accumulate for months after a premiere, so without it the pass
reads a current-season entry's empty vote count as a verdict, and the queue fills
with shows that simply have not been seen yet. An **undated** media is excluded
too: a NULL `aired_from` fails the comparison, and
proposing deletion is the wrong place to guess at an age.

*Standalone* is the gate that carries the rule. Plenty of real franchises carry
an unrated OVA or special, and those are side-entries of something that exists —
only an anime whose **entire** media set never drew votes is noise. Dropping that
condition floods the queue with franchise side-entries that should never be
proposed.

### Removal is media-grained

One candidate is one media. The anime is deleted only when its last media goes.

That is what lets a single dead entry leave a large franchise without touching
the rest: a 404 on one of a detective franchise's dozens of entries removes that
entry, while a 404 on a standalone film removes the anime with it. An anime-grained
queue could only express the second.

When the anime survives, the surviving set is **reclassified** — the deleted media
may have been the anchor, and `anime.mal_id` tracks the anchor's mal_id.

### What deletion costs

Everything keyed on `media.id` cascades, user-scoped rows included — so deleting
a media destroys every user's rating, note, episode count and watch history for
it, and nothing else in the system would warn about that. The queue counts the
two a user would notice (ratings and watchlist entries) per row, and the confirm
dialog repeats them at the point of decision. The action is username-gated for the same reason; there is no
undo short of restoring a backup.

### Blacklisting is a separate choice

Deleting removes the entry. **Delete + block** additionally records the mal_id in
`media_unwanted` with reason `Admin curation`, which takes it out of the seasonal
sweep's dedupe set, the relations probe's exclusion set and the search BFS — so
nothing re-adds it.

The two are separate because rediscovery is sometimes correct. An announced show
MAL pulled may be re-listed once it is funded again, and blocking it permanently
would be the wrong call; an entry MAL deleted because it never should have been
there should stay gone. This mirrors the distinction the scraper already draws
between skipping silently and recording in `media_unwanted` — see
[scraping](scraping.md).

**The checkbox defaults to off**, because the two mistakes are not symmetric.
Forgetting to block costs one more trip through this queue when a later sweep
rediscovers the entry. Blocking wrongly is permanent — nothing in the API or the
UI removes a `media_unwanted` row, so the only route back is a manual DB edit.

A blacklisted mal_id is rejected **before** the BFS runs, not after. The BFS
subtracts its own seed from the exclusion set (a seeded scrape has to be able to
fetch its seed), so the gate has to sit ahead of it — and unlike Hentai or a PV,
an admin-curated removal is otherwise ordinary content that no downstream content
gate would stop.

There is deliberately no un-blacklist UI. `BaseDAO.delete_all_by_field` is the
primitive if one is ever wanted.

### A 404 stops re-checking

Every other refresh failure leaves `MediaFreshness.last_checked_at` untouched, so
the media re-selects next sweep and retries. A 404 is permanent, so it stamps the
clock instead, dropping the row to the long-tail window. Without the stamp the
media stays permanently past its due window and burns a MAL call every single
night.

The stamp also advances the stability counter, which is the load-bearing half:
the stabilizing tier is a bare `stable_check_count < 3` with no staleness term,
so a recently-scraped media would otherwise stay due nightly no matter what the
clock says.

**Raising the candidate and stamping the clock are atomic** — both land in the
savepoint the refresh already holds for that anime, so the queue can never be
missing an entry whose clock was moved.

It is scoped to 404 alone. A 5xx, a 429 or a timeout is MAL being down, and
backing off on those would let one bad night push the whole catalogue to a 90-day
cadence — the failure the sweep's circuit breaker exists to bound.

Self-healing falls out of it: if MAL restores the entry, the next check picks it
up with no admin action.

## Where a candidate surfaces

- **The bell** pins an "Admin tasks" row summing every queue, from
  `GET /admin/curation/pending-counts`. Its unseen badge counts
  pending-minus-acknowledged, so a fresh login surfaces the work and opening the
  bell clears it.
- **The Jobs Log** tints a sweep row when it raised delete candidates. The tints
  are single-winner; `rowTintClass` owns the ranking and its reasoning, and
  USER_FLOWS §12.1c owns what the admin sees.
- **The job detail page** lists the sweep's 404s in a card of their own;
  USER_FLOWS §12.1d owns what the admin sees.

---

**Why it is this way**
- [Split candidates](../../compound-docs/2026-05-18-v0.14.2-split-candidates.md) — the split queue's origin
- [Classifier redesign](../../compound-docs/2026-05-16-v0.14.1-search-and-data-fixes.md) — what the merge signals are derived from
