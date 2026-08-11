---
description: How work gets done in this repo — approval, commit blocks, the review pipeline, and authoring style. Always loaded.
---

# Working agreement

Always loaded, so it stays short. Topic depth lives in the path-scoped rules
beside this file; doc placement lives in `docs.md`.

## Ask first

- **Never** create commits, branches on the user's behalf, issues, milestones,
  releases, or push code without asking. Present the plan and wait.
- Surface **design decisions before writing code** — API shape, enum semantics,
  one endpoint vs two. The user has strong opinions here and catches better
  designs than the first plan; picking silently wastes the work.
- **Read the relevant `docs/features/` doc while planning**, before settling on an
  approach. They don't load automatically (root `CLAUDE.md` indexes them), and they
  are where a subsystem's current behaviour is written down whole — the constraint
  that invalidates a plan is usually in there rather than in the code you'd read
  first.
- **Don't push after committing.** Stop at the commit. The user controls push
  timing so they can tag first, batch several commits, or hold one back —
  an auto-push also fires CI mid-stream.

## Commit blocks

Work is committed in **blocks**: one coherent, reviewable change each.

- **Bundle upward.** Three small fixes are one block, not three pipeline runs.
  ~100 LOC is a reasonable floor; it is judgment, not arithmetic.
- **Never carry an unreviewed block into the next step of a plan.** Finish a
  block → `/ship` → commit → *then* start the next. Deferring review to the end
  forces untangling of intermixed changes, which is the failure this prevents.
- **Plans declare their commit blocks up front**, so boundaries are agreed
  before implementation rather than negotiated over a dirty tree.

## Every commit goes through `/ship`

`.claude/hooks/review-gate.sh` enforces it. The skill owns the steps; the
hook owns the exemptions.

Changing the gate means running `.claude/hooks/test-gate.sh` and adding a case
for whatever you changed. Its failures are all fail-*open* — a gate that wrongly
allows looks identical to one that works, so the tests are the only symptom.

It is a speed bump, not a boundary: it cannot see mutations made earlier in the
same command, and its parser only recognises `git` in first position. The hook's
own header lists the gaps. Rely on it to catch drift, not evasion.

## Opening a PR

`/pr` runs what only makes sense once per branch: the full test suite, the ISO 25010
review panel, a re-`/ship` when that review changed anything substantial, and the
compound doc. It **stops before pushing** — push and PR creation need approval like
any other repo change.

## Commit messages

`<type>(v<version>): <subject>` — the scope is the release the work ships in,
so history groups by release without needing tags.

```
perf(v0.15.4): memoize the query embedding encode
fix(v0.15.4): PK tiebreak on every newest-first ordering
```

Types in use: `feat`, `fix`, `docs`, `perf`, `refactor`, `test`, `ci`, `build`,
`chore`. Subject is lowercase, imperative, and says what changed — not which
files. The body carries the *why* when it isn't obvious.

**Never reference plan-local constructs** — "phase 2", "block A", "step 3 of the
plan". They mean nothing once the plan is gone, which is immediately. This
applies to every durable artifact: commit messages, PR bodies, code comments,
docs. Describe the change on its own terms.

## Authoring style

- **Comment the design decision, not the code.** Explain *why* something is the
  way it is where that isn't self-evident. Don't narrate what the line does.
- **Present tense, not history.** State the current rule and its constraint —
  "it must stay X, because the obvious alternative Y does Z". Not "was
  superlinear before v0.15.4", not before/after numbers, not migration ids.
  Those belong in `compound-docs/`, commit messages, and PR bodies, which are
  dated and frozen; a living doc accumulates that narration every release and
  nobody prunes it. A durable *characteristic* ("~30 ms per encode, ~0.1 ms on
  a hit") is a current constraint and stays.
  Self-check before committing: grep added lines for `was `, `were `, `used to`,
  `previously`, `replaced`, `until v`.
- **Don't write counts that go stale.** "the five docs without a version",
  "four cron endpoints", "31 compound-docs" — each is correct until the next
  addition and then quietly wrong, with nothing to catch it. Describe the set by
  its property ("docs whose filename carries no version") instead. Same failure as
  a version stamp: a fact that decays without anyone touching it.
- **Hardcode design decisions; don't parameterize them.** Before adding a
  config option or parameter, ask whether the frontend or user will ever need
  to choose differently. If not, hardcode it and comment why — the option costs
  API surface and frontend branching for nothing.

## Never commit the deployed URL

The production domain must not appear in any repo-bound artifact: source, docs,
commit messages, PR bodies, config examples. The repo is public and the domain
is operational attack surface. Deployment reads it from env vars
(`PUBLIC_API_BASE_URL`, `CORS_ORIGINS`); use `<your-frontend-domain>` or the env
var name in anything committed. If asked to write it into a file, flag it first.
