---
date: 2026-08-12
version: v0.15.4
branch: docs/claude-setup-frontend-restructure
topic: Frontend docs — give every fact one home, and verify instead of trusting
status: in progress
related:
  - 2026-08-11-claude-setup-restructure.md
---

# v0.15.4 — Frontend docs restructure

## Summary

`phsar/frontend/CLAUDE.md` was the last holdout of the one-fact-one-home rule and
the largest auto-loading file in the repo. It is now a 5,739 B map.

| | before | after |
|---|---|---|
| `phsar/frontend/CLAUDE.md` | 101,432 B / 218 lines | 5,739 B / 77 lines |
| `.claude/rules/frontend.md` | 2,846 B / 59 lines | 6,858 B / 136 lines |
| Auto-loaded for frontend work | 104,278 B | 12,597 B (**−88%**) |
| Version stamps in the doc | 97 | 0 |
| `USER_FLOWS.md` §13 | unverified | CI-pinned, 68/68 |

**The diagnosis was not "the doc is too long".** The doc's per-component prose was a
second copy of comments that already existed in the components. `filterLifecycle.ts`
is 2,490 B of which 1,320 B is a JSDoc block containing its doc bullet nearly word for
word; its bullet was *also* ~2,490 B. `EChart.svelte` is 65% comments and already made
every argument its 2,043 B bullet made. Frontend source carries **194,834 B of
comments — 24% of app source, 1.9× the doc** — and only 11 of 155 files have none.

So most of the work was deletion, not relocation. That inverts the risk profile: the
previous pass's five wrong corrections came from *writing* prose, and verified
deletion writes none.

## Key decisions

**A bullet may only be deleted once the fact is verified present in a named
destination.** Not "the source probably covers this" — a comment read in this session,
a rule, or `USER_FLOWS.md`. Every deletion was recorded as `doc line → destination
file:line`, and that worksheet is what the deletion commits were reviewed against.

**Homes before deletion, always.** See the failed approach below; this is the single
most important ordering constraint in the work.

**Absence facts get an explicit "we deliberately did not" comment.** A deliberately
*missing* thing — no tooltip on the search badge, no global 401 handler, no backend
probe in the liveness check, no per-user stats endpoint — leaves no code for a comment
to attach to, so it is the one class that genuinely has no home. These were the only
real losses in the components pass and the only gap in `lib/`.

**Cross-module facts go to `.claude/rules/frontend.md`, not a feature doc.** A fact
that is a choice *between* components (which of three tooltip mechanisms; which toggle
for which surface) is read while writing the code that would violate it. A
`docs/features/` doc does not auto-load and arrives too late.

**The frontend gets no `docs/features/` doc, and no new rule either.** Each candidate
was tested against "is there a cross-module fact that neither a rule nor any single
file owns?" — charts (17 files entangled), share (7), watchlist (20), spoilers (11) all
failed the test, because `EChart.svelte`, `ShareDialog.svelte`,
`stores/watchlist.ts:5-8` and the existing `spoilers.md` already own their subsystem.
The one candidate gap, the contract for adding a section filter, turned out smaller
than claimed (below) and landed in `persistedFilter.ts`'s header.

**`USER_FLOWS.md` keeps observable behaviour; the source keeps the reasoning.** The
five duplicated facts existed because the old split was by *kind* of fact rather than
by subsystem — "30s instead of 60s because the seasonal sweep window can be seconds
long" is behaviour and implementation inseparably, so a kind-based split has no correct
home for it and it landed in both files.

**The routing tables name areas, not files.** A per-component list decays on every
addition; the areas hold. This is the sink fix — the file grew 99 → 101.4 KB in the
days before this work and now has nothing to accumulate.

## Failed approaches

**Deleting the components section before its destinations existed.** The first attempt
removed the three-tooltip-types taxonomy in the same pass that was supposed to precede
the rule holding it. An adversarial review found **9 facts lost out of 47 sampled**
(19%). The second attempt, with homes written first, lost 1 of 46. Nothing about the
content changed between attempts — only the order. The lost set is worth naming because
it characterises what source comments *cannot* hold: the tooltip taxonomy (a choice
between three mechanisms), the native `title=` rationale, `MediaInfo`'s deliberately
absent tooltip, `ScorePercentile`'s must-stay-grain-agnostic copy, `Notice`'s opaque
surface, `SweepTiersCard`'s ROWS/total invariant, the curation same-tab link decision,
the `resolveTitle` rule, and the `emphasis: { disabled: true }` chart convention.

**Trimming `rules/frontend.md` to reduce its size.** Both cuts removed load-bearing
content and were reverted. `SegmentedControl.svelte` never says what to use on a *dark*
surface — its only "dark" is the token name `card-foreground (dark)` — so deleting the
toggle-surface rule left `## Shared components`' push toward unification with no
counterweight, since that rule was its stated exception. And the shortened route-title
section dropped the detail-page clause, which is the coupling point to the `resolveTitle`
rule; without it the rule reads as a static page name. The file ended up **larger** than
before the trim (6,858 vs 6,742 B). The size concern was unfounded: it earns it.

**Claiming a cross-user leak in the filter contract.** Asserted that a new section
filter could skip the per-user reset and leak user A's list uuids to user B. It cannot:
`createPersistedFilter` registers its own reset (`persistedFilter.ts:87`) and
`resetAllPersistedFilters()` is already in `clearPerUserStores`
(`routes/+layout.svelte:49`). The registry exists precisely to make that unmissable.
Only the *section* wiring is manual, and its failure is a stale filter, not a leak —
which is why it became one sentence at the factory instead of a rule.

**Measuring comment coverage with a regex that only matched JS comments.** Reported 169
KB / 21%, missing the HTML comments Svelte templates use heavily. A second attempt with
a broken awk state machine (`next` skipped the close-tag detection, so once a comment
opened every later line counted) reported 505 KB / 63%. The correct figure is 194,834 B
/ 24%. Two wrong measurements in a row on the number the whole diagnosis rests on.

## Gotchas & learnings

**Every error found in the old doc was in an *inventory*, never in rationale.** Of ~48
audited claims, 45 were correct; the three wrong ones were `createPersistedFilter`'s
signature (a documented `preserveOnClear` option and `{store, clear, reset}` return that
do not exist — it returns a bare `Writable<T>`), the `api.ts` method list omitting
`patch` (which the doc itself used elsewhere), and `resetAllPersistedFilters` attributed
to `auth.ts`, whose own comment says the opposite. Narrative rationale was accurate down
to individual constants — because it was written alongside the source comment it
duplicates. **The most accurate content was the most duplicative.**

**Verifying found six real defects that were not the goal:**

- `SweepTiersCard` claimed **4** cycle-membership tiers where its own union has **5**,
  and its `total` sums that array while the header advertises a catalogue-wide sum — so
  a tier added backend-side and omitted there breaks the claim silently. The deleted doc
  line had been right. Its pointer at `jobs.md` was also wrong: that doc's due-ness
  tiers deliberately count the long tail differently, which is plausibly where the stale
  4 came from.
- The admin page claimed **"no card polls"** in the doc *and* in its own comment. The
  jobs log polls in an ungated `$effect` while eager-mounted, so an admin parked on
  Overview requests `/admin/jobs` every 30s.
- `USER_FLOWS` §12 listed the job-detail sections in reverse render order and named a
  heading the page does not use.
- The `DetailOrigin` union has **seven** members; the doc listed six. `?from=ratings`
  was live and undocumented. Its "extending surfaces as a type error" claim was false —
  `BackLink` is an if-chain with no exhaustiveness check.
- `api.ts` cited a 60s banner poll against `MaintenanceBanner`'s 30s.
- `persistedFilter`'s `pickKey` docstring sat above `Direction`, so the destination
  rendered the wrong doc.

**Four rules were written as universals and had real exceptions.** Caught before
landing, by review: SSR is on and only *data loading* is client-side (`+layout.ts:28`
guards `if (!browser) return`); the score gauges legitimately have no chart tooltip; a
restricted account loses a *single control* to an inert state but a *whole section* to
an explanatory replacement (three sites replace rather than disable); the two statistics
tabs differ on mounting deliberately. The restricted-account one mattered most —
followed literally it would have had someone rewrite three correct sites.

**`authoring-rules.md` was wrong about `paths:` on the CLI version it cited.** It
declared a YAML list and a glob without a trailing `/*` non-loading, and its heading
required a single string ending in `**/*`. Eight headless runs on 2.1.128 show all three
claims wrong: lists load, `dir/**` loads, a single named file loads. **One run returned a
false negative and passed on every retry** — which is the likely origin of the original
table, and why the rule now says to repeat an absent answer before believing it,
including the negative arm.

**Narrow `paths:` scoping is available but usually wrong.** A rule scoped to the files
that already follow it loads where the convention is kept and stays silent in the new
file about to break it — an enumeration of today's charts cannot match tomorrow's. The
distinction that matters is **directory-shaped over content-shaped**; all six rules
already satisfy it.

**A doc's reliability is itself a fact the reader needs.** `frontend/CLAUDE.md` is now
audited and `USER_FLOWS.md` is not, and nothing told them apart. Its header now
calibrates: §13 pinned by a test and unable to drift, behavioural sections not
systematically verified with errors concentrated in the longest ones. Written to
*narrow* as sections get checked rather than to stand as a blanket disclaimer.

**Pin what a machine can check; say so about the rest.** §13's 68 endpoint rows are now
asserted against `create_app()`'s real route table rather than parsed from decorators —
reconstructing the paths means reimplementing FastAPI's prefix nesting (`admin.py`
mounts four sub-routers declaring no prefix, plus a `/backups` one that does), and a
parser that gets that subtly wrong reports success while checking nothing. Verified to
fail on a bogus path, on a wrong method for a real path, and on the table's format
changing so no rows parse — that last case being the only way it could silently stop
checking, so it fails closed on a row-count floor.

**Sampling sized the remaining risk.** `USER_FLOWS.md`'s tabular content is clean (68/68
endpoints); a 6-claim sample of §12's behavioural prose found 1 wrong, and 3 of the 4
errors found incidentally were also behavioural prose in §7/§12. Extrapolating over
~296 behavioural claims gives roughly 30–60 wrong — wide error bars on a small sample,
but not near zero.

**The review panel earned its cost twice.** Once catching the 9 lost facts, once
catching the four overstated rules. Both were invisible from the inside: a deleted fact
leaves no symptom, and a rule that reads confidently is indistinguishable from a rule
that is right.

## Future work / debt

- **`USER_FLOWS.md`'s behavioural sections have never been audited against source.**
  §6, §7 and §12 are 52 KB, 54% of the doc, and where every error so far has been.
  Estimated 30–60 wrong claims. Wants its own branch: verify each claim before
  rewriting it, since five of the previous pass's corrections-from-review were
  themselves wrong.
- The frontend stack sentence appears in root `CLAUDE.md`, `rules/frontend.md` and
  `frontend/CLAUDE.md`. Left deliberately: one clause, it does not drift, and each copy
  orients a different reader.
- `docs/ROADMAP.md`'s share-design section overlaps the share source. Left deliberately:
  the roadmap holds the *why*, the modules hold the *how*, which is the correct split.
- `main` is behind this branch's base. The PR base is `v0.15.4-efficiency-improvements`,
  against which this branch is exactly its own commits; against `main` it is 41.
- Untouched, outside this branch: `shellcheck` over the hooks, a shared
  `scripts/lint.sh`, and the six `.claude/agents/*-reviewer.md` duplicates — that last
  one still needs a delete-or-adapt decision.
