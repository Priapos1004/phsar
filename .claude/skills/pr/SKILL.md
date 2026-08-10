---
name: pr
description: Open a pull request — full test run, ISO 25010 review panel, re-ship if the review changed anything substantial, compound doc, then stop for approval before pushing.
argument-hint: [PR title or focus]
---

# Open a pull request

Runs the checks that only make sense at PR time, then **stops before pushing**.
Pushing and opening the PR need explicit approval, every time — see
[.claude/rules/workflow.md](../../rules/workflow.md).

## 1. Scope the branch

```!
git status --short
git log --oneline main..HEAD
git diff --stat main...HEAD
```

Everything below reviews `main...HEAD`, not just the last commit. If the working
tree is dirty, `/ship` it into a commit first — the review must cover what will
actually merge.

## 2. Tests

```
cd phsar && pytest
cd phsar/frontend && bun run test
```

`/ship` deliberately skips these — they need the database container, so they are a
poor fit for a per-commit gate. PR time is when the container is expected to be up
and when a full run has to pass. **Do not skip them.** If the container isn't
running, say so and stop rather than opening a PR on unrun tests.

`ruff check .` and `bun run check` have already run per-commit via the gate.

## 3. ISO 25010 review panel

Launch all six reviewers **in parallel** (one message, six Agent calls), each with
the full `main...HEAD` diff:

| Agent | Looks for |
|---|---|
| `functional-suitability-reviewer` | completeness, correctness against intent |
| `reliability-reviewer` | error handling, fault tolerance, recovery |
| `security-reviewer` | injection, secrets, auth, OWASP |
| `performance-reviewer` | time behaviour, resource usage, capacity |
| `maintainability-reviewer` | modularity, dead code, duplicate imports, DRY |
| `flexibility-reviewer` | adaptability, installability, environment coupling |

Tell each agent the stack explicitly — FastAPI + SQLAlchemy async + PostgreSQL/pgvector
backend, SvelteKit + Svelte 5 frontend — and point it at the relevant
`.claude/rules/` file so it reviews against this repo's invariants rather than
generic ones. Ask for `file:line` and a concrete failure scenario, not vague
observations.

Dedupe findings that point at the same line or mechanism, then fix them. Skip any
whose fix would change intended behaviour or reach well outside the diff — **state
the skip and why**, don't argue with it silently.

## 4. If the review changed anything substantial, ship again

Review fixes are new, unreviewed code. When step 3 produced more than trivial
edits, **run `/ship` over them** — docs, simplify, lint — and commit before going on.

This is not optional tidiness: the ISO panel routinely lands real changes, and
without this they would reach the PR having had neither the simplify pass nor a
docs update. Repeat until a review round produces nothing substantial.

## 5. Compound doc

**First look for a provisional doc for this branch** — `compound-docs/` entry whose
`branch:` matches, or whose `status:` is in-progress / running notes. A long branch
usually has one, because earlier sessions write knowledge down as they go.

**If one exists, rewrite it — do not extend it.** Those are deliberate knowledge
dumps: each session appends what it learned, so the file arrives verbose,
chronological and full of narration that a reader does not need. Its *content* is
the raw material; its *shape* is not. Read it whole, keep the decisions, the failed
approaches and the gotchas, and throw away the running commentary, the per-session
ordering, and anything the diff already shows. A 500-line running record usually
distils to well under a hundred.

Then set `status: shipped` and make the date the PR date.

**If none exists**, copy [compound-docs/TEMPLATE.md](../../../compound-docs/TEMPLATE.md)
to `compound-docs/YYYY-MM-DD-<slug>.md` and fill it in. Check first whether an
existing doc already covers the area — extending one beats a near-duplicate.

Either way it records **why**, not what: decisions with their rejected alternatives,
approaches that failed, non-obvious gotchas. Not lint or test status, not a change
list — the diff already says what changed.

Add it to `compound-docs/INDEX.md` in **both** groupings.

Then `/ship` this doc as its own commit.

## 6. Stamp the PR marker

```
.claude/hooks/mark-pr-ready.sh
```

Last, after the compound doc is committed — it records the branch tip SHA, and
`review-gate.sh` refuses `gh pr create` when that SHA isn't the current one. Stamping
before the commits in steps 4 and 5 would vouch for a tip that didn't exist yet.

## 7. Present, and stop

Report: test results, what each reviewer found, what was fixed, what was skipped and
why, and the proposed PR title and body. Then **stop and wait**.

On approval:

```
git push -u origin <branch>
gh pr create --title "<title>" --body "<body>"
```

Never force-push.

### PR body

```markdown
## Summary
<what this changes and why>

## Changes
- <the substantive ones; the diff covers the rest>

## Review
ISO 25010 panel: <findings fixed> fixed, <skipped> skipped (reasons inline below).
Tests: pytest <result>, vitest <result>.

## Compound doc
compound-docs/<filename>.md
```

$ARGUMENTS
