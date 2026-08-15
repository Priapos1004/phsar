---
date: YYYY-MM-DD
version: vX.Y.Z
branch: <branch-name>
topic: <one line — what this work was about>
status: shipped
related:
  - <other compound-doc filename, when one is genuinely a prerequisite>
---

# vX.Y.Z — <title>

<!--
Copy this file to compound-docs/YYYY-MM-DD-<slug>.md and delete these comments.

A compound-doc records WHY something changed: the decision, the alternatives that
lost, what failed. It is dated and frozen — later work supersedes it rather than
editing it. How the system works *now* belongs in docs/features/.

LIFECYCLE: on a long branch, sessions may keep a provisional doc with
`status: in progress` as running notes. That file is raw material, not a draft —
/pr REWRITES it into this shape at PR time rather than tidying it, because the
running commentary and per-session ordering are exactly what a later reader
doesn't want. Expect a large reduction.

Do NOT include: lint/test status (CI owns that), line-by-line change lists,
obvious implementation detail, or anything a reader could get from the diff.

Add the doc to compound-docs/INDEX.md in BOTH groupings, or it is half-invisible.
-->

## Summary

Two or three sentences. What changed and why it mattered.

## Key decisions

The load-bearing ones, each with the alternative that lost and why. A decision with
no rejected alternative usually wasn't a decision — drop it or say what it rules out.

Tuned constants belong here with the warning attached: what they were validated
against, and what re-validation a future change needs.

## Failed approaches

*Only when something was genuinely tried and abandoned.* What was tried, why it
looked right, and what killed it. This is the section a future reader benefits from
most, because it is the only place the dead ends are written down.

Omit the heading entirely when nothing failed.

## Gotchas & learnings

Non-obvious things discovered along the way — an upstream quirk, an ORM trap, an
ordering requirement. If it constrains future code, it also belongs in
`.claude/rules/`; if it describes current behaviour, in `docs/features/`. Here it is
the story, there it is the rule.

## Future work / debt

*Only when there is any.* What was deliberately left, and what would trigger doing
it. Omit the heading otherwise — an empty "none" section is noise every reader pays
for.
