---
date: 2026-08-11
version: v0.15.4
branch: docs/claude-setup-restructure
topic: Claude Code setup — enforce the review pipeline, give every fact one home
status: shipped
related:
  - 2026-08-12-frontend-docs-restructure.md
  - 2026-08-06-v0.15.4-efficiency-improvements.md
---

# v0.15.4 — Claude Code setup restructure

## Summary

Two problems with one shape: a fact nobody owned. The commit pipeline existed only
as a private memory note, which reaches Claude as background context rather than
instruction, so it got skipped under context pressure; and the docs cost ~21,000
tokens every session before any work began, duplicated in a dozen places counted
at the time, several already drifted apart. The pipeline is now a `PreToolUse`
hook, and every fact has one home.

Measured at this branch tip, against `v0.15.4-efficiency-improvements`. The
always-loaded set is root `CLAUDE.md` plus `.claude/rules/workflow.md`, the one
rule with no `paths:` scope; chars are the durable figure and the token column
is a division, so treat it as a range.

| | before | after |
|---|---|---|
| Always-loaded | 80,299 chars | 20,974 (**−74%**) |
| — as tokens, @3.8–4.2 chars | ~19,100–21,100 | ~5,000–5,500 |
| Root `CLAUDE.md` | 483 lines / 78 KB | 288 / 15 KB |
| `services/CLAUDE.md` | 81 KB | 14 KB |
| Version stamps in root | 49 | 2 |

The skill and agent `description:` frontmatter the branch adds also loads every
session (~2,400 chars), and is not in the table — counting it, the cut is ~71%.

## Key decisions

**The gate verifies the union of the index and the whole uncommitted worktree,
rather than detecting which one git will commit from.** Detection was tried and
is the origin of most of this branch's defects — see below. The rejected
alternative is the obvious one: parse the command, decide whether it commits the
index or the worktree, check that. The union needs no parsing, is a superset of
every command form, and matches exactly what `mark-reviewed.sh` stamps. It costs
strictness — an unreviewed edit to a file you are *not* committing also denies —
which is the correct direction for a mechanism whose every historical defect has
been fail-open.

**Blob hashes, not timestamps.** mtime is wrong in both directions: `git stash
pop`, a branch round-trip and any rebase rewrite byte-identical files with fresh
mtimes, forcing a re-run of a pipeline whose steps are minutes-long review
passes; and second-granularity stamps let an edit inside the same second pass
unreviewed. A hash answers the question actually being asked.

**Marker lines carry the path, not just the hash.** A bare hash set lets a
brand-new or renamed file validate against some unrelated file's reviewed
content — and an empty new file passes permanently, because the empty blob
enters the marker the first time `/ship` ever runs over one.

**The gate is documented as a speed bump, not a boundary.** Its header used to
claim it "cannot be talked past". That is false and worth stating plainly,
because a doc that overstates a control is worse than no doc: the hook fires
*before* the command runs, so `echo x >> f && git commit -a` commits content no
`/ship` ever saw, and no state inspection can fix that. It protects against
drift under context pressure, which is the actual threat, and not against
anyone stepping around it.

**Rules are path-scoped so they load only when relevant**, rather than kept in one
always-loaded file where every session pays for every rule. That is the whole
mechanism behind the context saving; `authoring-rules.md` documents the glob
forms that work, because a glob matching nothing fails silently.

## Failed approaches

**Detecting whether a commit takes the index or the worktree.** The first fix for
the untracked-file hole read the index, since that is what a plain `git commit`
uses. This immediately reopened three bypasses — a pathspec commit
(`git commit -m x path/f.py` takes the worktree copy whatever the index holds),
`-i`/`-o`/`--only`, and `-am"msg"` where a flag regex of `-[a-z]*a[a-z]*` misses
the quoted glued form — and added two fail-*closed* bugs. Each round of
detection fixed the forms someone had thought of and missed the next one. The
lesson generalises: when a check depends on enumerating variants of attacker- or
author-controlled syntax, prefer a superset that needs no enumeration.

**`PostToolUse` on the `Skill` tool to stamp the review marker.** It fires when a
skill is *loaded*, not when its work finishes, so `/ship` would stamp before
`/update-docs` and `/simplify` had edited anything, and the gate would then
reject the commit it had just correctly reviewed. Having the skill stamp as its
own final step is both correct and one hook fewer.

**`stat -f %m` for marker freshness.** BSD-only — on GNU coreutils `-f` is
`--file-system` and `%m` is *mount point*, so it returns `/`, the arithmetic
evaluates false, and the gate passes every commit on Linux while `CONTRIBUTING.md`
advertises it as enforcement. Drove the switch to git blob hashes, which are
portable and answer a better question.

**Concluding `paths:` gating was unsupported.** It works; a rule whose glob matches
nothing loads never — indistinguishable from an unsupported feature, with no error
either way. Had the rule files shipped mis-scoped while root `CLAUDE.md` was
stripped in the same pass, the content would have loaded nowhere. The specific
forms blamed here were themselves diagnosed from single runs and are wrong —
`authoring-rules.md` carries the measured set, and the lesson generalises to
"verify, and repeat an absent answer" rather than to any one glob shape.

**Verifying a rule with a question other docs can answer.** The first load test
asked about facts that also appear in the always-loaded root `CLAUDE.md`, so a
correct answer proved nothing either way.

## Gotchas & learnings

**Every gate defect found has been fail-*open*, and that asymmetry should drive
the review.** A gate that wrongly blocks is noticed in seconds; one that wrongly
allows is invisible and looks healthy. The list is long: chained
`git add -A && git commit` resolving to `add`; a missing `jq` allowing everything
and unable to report it; macOS bash 3.2 treating an empty array under `set -u` as
unbound, zeroing a size check; a failed hash read counting as verified; untracked
files being stamped by the writer but never read by the checker; deletions
filtered out of the very set that decides whether review applies; one unhashable
path emptying the whole fingerprint. When reviewing any gate, ask specifically
for silent-allow paths rather than for bugs.

**Which is why the tests exist.** `test-gate.sh` drives the real hook in
throwaway repos and asserts each verdict. It is not ordinary coverage: for a
fail-open defect there is no symptom to notice, so the test is the only reporting
channel. It grew from 11 cases to 30 during one review round, and every case
added came from a hole that was live at the time.

**Corrections need the same verification as the claims they replace.** Round one
of the doc fixes was written from review findings rather than from source, and
five were themselves wrong — including a CORS failure mode that does not exist
(compose supplies its own `:-` defaults), `/auth/refresh` described as a public
write when it is authenticated and merely role-ungated, and a claim that only the
relation-link signal feeds `detect_merge_candidates` when it runs the title
signals itself. A review pass over the corrections is not paranoia.

**A fix applied in one place when the wrong claim exists in three is not a fix.**
`spoilers.md`, `search.md` and `USER_FLOWS.md` all asserted that the frontier sort
keys never disagree, when the client walk tiebreaks on `uuid` and the backend on
`mal_id`. The first pass corrected only `spoilers.md`, leaving the other two
stating the opposite of the file next to them; a review pass caught that before
it landed, so all three moved in one commit. After correcting any fact, grep the
repo for other copies of the old one.

**Sub-agent review caught assertions written but never checked** — routes that do
not exist, "services are never classes" when three are, a named test that has
never existed, and a rule stating every write endpoint gates on
`require_user_or_admin` when admin writes gate on `require_roles(Admin)`. That
last one would have put admin mutations within reach of any user account if
followed. Cheap relative to what a wrong rule costs, since a wrong rule gets
followed.

**`grep -v '^$'` inside a pipeline under `set -e` and `pipefail` is a trap.** grep
exits 1 when nothing matches, and an empty result is a perfectly normal state, so
the subshell dies mid-pipeline. It silently wrote an empty marker for a
deletion-only `/ship`. `sed '/^$/d'` exits 0, which is why the shared helpers use
it. Worth knowing that the rule was written into `state.sh`'s header and then
broken one file away in the same sitting, caught only by review — the shape is
easy to reintroduce precisely because an empty result looks like an error and
isn't. It survives in `review-gate.sh`, which is safe only because that file
deliberately runs without `set -e`.

**A stacked branch breaks any tool that hardcodes `main`.** `/pr` did, in four
places. Running it on a branch based on a release branch would have fed the
review panel hundreds of lines of already-reviewed parent-branch code and then
stamped `pr-ok` over a range nobody reviewed.

## Future work / debt

- **The pre-mutation window** (above) would close by refusing any commit chained
  after a content-mutating segment. That blocks legitimate work, so it is a
  design call rather than a patch.
- **Command-shape prefixes are unhandled**: shell keywords (`if true; then git
  commit`), wrappers (`time`, `command`, `exec`), env prefixes, absolute paths.
  Reviewers split on whether to close them, given `GATE_BYPASS=1` exists as a
  sanctioned exit.
- **`git hash-object` dereferences symlinks** while git stores the link target, so
  a file swapped for a symlink can match a stale marker. `git add -N` (used by
  `git add -p` on new files) is unshippable for the mirror reason.
- **Both stampers are on the permission allowlist**, so either marker the gate
  trusts can be produced without a prompt.
- `phsar/frontend/CLAUDE.md` is not restructured — 99 KB when this shipped, the
  largest auto-loading file in the repo and ~81% of a frontend session's loaded
  context; only a cross-reference in it changed here.
- Root `CLAUDE.md` still duplicates parts of `docs/features/`. Its rules table no
  longer restates each rule's glob — a second copy of frontmatter that could only
  decay.
- The six `.claude/agents/*-reviewer.md` are byte-identical copies of an installed
  plugin's agents. `/pr`'s panel table names them bare, but only the
  `onethousand:`-prefixed names resolved in the session that ran the panel, so
  which copy actually runs is unclear. Either delete them or adapt them to this
  stack and confirm the bare names resolve.
- No `shellcheck` over the hooks that now gate every commit.
- One `scripts/lint.sh` shared by CI, `/ship` and the gate would remove three
  definitions of "what lint means here"; the gate's value depends on agreeing
  with CI.
