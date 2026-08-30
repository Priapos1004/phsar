# Continuity across a navigation

What comes back when a user leaves a page and returns to it — and which carrier
brings each part.

**Code**: `utils/returnTo.ts` (the route) → `utils/navigation.ts` (the origin) →
`utils/scrollFocus.ts` (the position) → `stores/persistedFilter.ts` +
`utils/resumeSession.ts` (the filters) → `utils/filterLifecycle.ts` (when each
resets).

## What travels, and on which carrier

| What comes back | Carrier | Owner |
|---|---|---|
| the route a departure for /login left from | `?next=` on the /login URL | `returnTo.ts` |
| which list a detail page was opened from | `?from=` / `?q=` / `?job=` | `navigation.ts` |
| the position in that list | `?focus=` on the back link | `scrollFocus.ts` |
| that list's controls — filters, and the Jobs Log page | per-tab `sessionStorage` | `persistedFilter.ts` |
| those controls across a *lapsed session* | the `phsar.resume` stash | `resumeSession.ts` |

**The URL carries whatever belongs to one link.** Two tabs open on two different
searches must not share an origin or a scroll position, and a link handed to
someone else has to arrive carrying nothing of the sender's. Anything per-link
therefore lives in the URL, where it also dies with the navigation and needs no
reset. `absoluteDetailUrl` is what enforces the second half: a share URL is rebuilt
from the uuid rather than copied off the address bar, which is carrying all of it.

**Storage carries whatever cannot fit in a URL.** A filter set is too large and too
structured for one. It is `sessionStorage`, so it is per tab and cannot greet the
user next week.

**Neither carrier reaches on its own, which is why both exist.** A hard
`window.location.href` hands nothing forward to the next page, so the filters need
storage; a shared link opened in a fresh tab has no storage to read, so the route
needs the URL. `returnTo.ts` and `resumeSession.ts` are two halves of one
round-trip for that reason, not two designs.

## The route and the origin

Consuming a `?next=` goes through `safeReturnPath`, always — `rules/frontend.md`
states that invariant and tabulates which helper each kind of departure uses;
`returnTo.ts` argues the validation and why it refuses to keep a route allowlist.
A path carries its own `?tab=`, so restoring one restores the section a user was
looking at, not just the page.

The origin markers ride `buildDetailHref`'s options bag, and every anime↔media jump
rebuilds the href with the whole bag intact, so a deep dive stays linkable back to
where it started. `navigation.ts` owns the bag and the closed `DetailOrigin` set;
USER_FLOWS §7.6 owns what each one renders.

## The position

The back button is a forward `<a href>` rebuilt from URL params, so the browser's
own scroll restoration never fires — that runs on popstate only, and no back button
here is one.

The detail page **is** the item that was clicked, so its own `uuid` is the default
anchor and no list has to build a focus-carrying link. That is what keeps the list
side down to one `data-focus-uuid` attribute per component. A `focus` already on the
URL wins, which is what makes a deep dive return to the anime card rather than the
media one.

A page must render the target before it can centre it. Only `/search` has to act on
that: its whole result set arrives in one request and is sliced behind "Show More",
so it expands far enough first. `scrollFocus.ts` argues the timing, which is the
part that is not obvious.

## The controls

Two mechanisms, for two different departures.

**Across an ordinary navigation** the live per-tab stores hold them —
`persistedFilter.ts` owns the version envelope, the mandatory sanitize and the
self-registering registry that makes whole-set operations safe. The Jobs Log's page
number is a field in its store rather than component state, so a job detour comes
back to the page it left; unlike the scroll position, restoring it refetches, since
the page is a query parameter.

**Across a lapsed session** the `phsar.resume` stash survives the token clear that
wipes the live keys. `resumeSession.ts` owns the owner check, the TTL and the
one-shot read; `rules/frontend.md` owns the call ordering, which is the part a new
departure site gets wrong.

## When each resets

Clear section S when navigating to a page that is neither inside S nor a detail
page. **A detail page is a detour, not a destination** — the user opened a row to
look at it and is coming back.

The reset runs from the root layout rather than each section's own, for a reason
that is easy to undo by accident; `filterLifecycle.ts` states it at the rule, along
with why SvelteKit's `snapshot` fits neither the filters nor the scroll position.
Both are app-owned and keyed on the URL, and they follow the same call because they
have the same lifecycle shape.

## Everything degrades to the default

No carrier can break a page by being wrong, which is what makes the set safe to
extend:

- a `next` that fails validation → a bare `/login`
- an unrecognised `from` → the search token, or no back button
- a `focus` matching nothing rendered → the list lands at the top
- a stash that is foreign, stale, or unparseable → the controls start clean

---

**Why it is this way**
- [Quality-of-life upgrades](../../compound-docs/2026-08-29-v0.15.5-quality-of-life.md) — splitting the round-trip across two carriers, and why the return scroll is held rather than timed
- [Ratings page](../../compound-docs/2026-06-23-v0.14.12-ratings-page.md) — the first section filter, and the lifecycle rule it forced
- [Watchlist](../../compound-docs/2026-07-23-v0.15.0-watchlist.md) — the second, and the parallel-pages constraint between them
