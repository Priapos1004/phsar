---
name: ship
description: Run the pre-commit pipeline on the current block of work — docs, simplify, lint — then present a commit plan for approval. Use before every commit; pre-commit-gate.sh blocks commits without it.
argument-hint: [optional note about the block being shipped]
---

# Ship a block of work

Runs the full review pipeline over everything uncommitted, then stops for approval.
Never commits on its own — the user approves every commit.

## 0. Scope the block

```!
git status --short
git diff --stat
git diff --cached --stat
```

Classify the change set — it decides which steps below apply:

- **Frontend files touched** (`phsar/frontend/**`) → step 1 applies.
- **Prose-only** — every path ends `.md` **and** no file was added, renamed or
  deleted → skip step 2 and go to step 3. Running `/update-docs` to commit a
  docs fix is circular. Adding or removing a file is *not* prose-only whatever
  its extension: it changes the tree and what other docs must point at.
- **Anything else** → all steps.

## 1. Frontend work stops for a human first

If frontend files changed, **stop here** and say: *"Ready for your visual review —
here's what to check: …"*, listing the affected routes/components.

`/simplify` judges design quality, not whether the page is right: spacing, contrast,
alignment, broken hrefs, and ignored user settings are invisible to it. Backend-only
work skips this step because pytest covers correctness; UI has no such net.

Resume at step 2 once the user has looked.

## 2. Update the docs

Invoke the **`update-docs` skill** via the Skill tool. It owns the target list — do not
hand-edit docs instead, because it reaches targets a manual CLAUDE.md edit reliably
misses (the `phsar/README.md` folder tree above all).

Docs come **before** `/simplify`, so that a single simplify pass reviews the new prose
along with the new code.

## 3. Simplify

Invoke the **`simplify` skill**. It reviews **documentation prose as well as code**.

**Never skip it on diff size.** A "tiny additive change" gets the same pass — the
review exists to catch what looks obvious to whoever wrote it.

## 4. Re-diff the README tree

`/simplify` can add, rename, split, or delete files that the step-2 docs pass never
saw. Re-run the tree check from the `update-docs` skill's Process step 1 — it owns the
command and its ignore list — and diff the result against `phsar/README.md`.

## 5. Lint

```
cd phsar && ruff check .
cd phsar/frontend && bun run check     # only when frontend files changed
```

Fix what surfaces (`ruff check . --fix` for the mechanical ones). Treat findings like
`/simplify` findings: fix, or skip with a stated reason. Report the result in step 7 —
CI runs `ruff check .`, and merging red wastes a CI cycle.

`pytest` and `bun run test` are deliberately **not** here: they need a running database
container, and CI runs them on every push. This step covers only what is fast and
always available locally.

## 6. Stamp the review marker

```
.claude/hooks/mark-reviewed.sh
```

Last, after every edit above. `pre-commit-gate.sh` compares this marker's mtime against
the newest changed file, so stamping earlier would vouch for work done afterwards.

## 7. Present the commit plan and stop

Propose commits as **logical blocks**, with the message for each — see "Commit blocks"
and "Commit messages" in [.claude/rules/workflow.md](../../rules/workflow.md). State the
lint result. Then **stop and wait** — the user approves before anything is committed.

## Re-entrancy

Fixes made *during* this pipeline are new unreviewed work. If step 3 or 5 changed
anything beyond trivial auto-fixes, re-run from step 2 — never bundle reviewed-A with
fresh-B into one commit.

$ARGUMENTS
