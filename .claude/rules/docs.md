---
description: Where a fact belongs, and how to write it. Loaded when editing any markdown file.
paths: "**/*.md"
---

# Documentation rules

## Where a fact belongs

Ask: **what breaks if this is missing?**

| Answer | Home | Loaded |
|---|---|---|
| Can't run or navigate the project | root `CLAUDE.md` | always |
| Would write code violating an invariant | `.claude/rules/<topic>.md` | when matching files are touched |
| Couldn't say how a subsystem behaves across the modules it spans | `docs/features/<topic>.md` | read while planning work in that area |
| Would re-litigate a settled trade-off | `compound-docs/` | on demand |
| Describes one module's current shape | docstring, or nearest nested `CLAUDE.md` | with the code |
| A feature decision not yet built, or the version table | `docs/ROADMAP.md` | on demand |

**No fact appears in two rows.** Cross-references are links, never restatements.
A doc that explains something *and then* says "see X for details" is both a copy
and a pointer — strictly worse than either, because the copies drift apart and
neither side knows which is current.

## When nothing fits, flag it

A fixed structure ossifies. Never invent a new doc, rule, or category alone, and
never wedge a fact somewhere it doesn't belong — **surface it, discuss it, then
place it.** Worth raising:

- a fact matching **no** row above;
- a subsystem whose content is spread over three or more homes, or that other
  docs keep cross-referencing — it may have earned a doc of its own;
- **two docs starting to duplicate** — a missing owner, not untidiness;
- **a rule that keeps getting violated** — often its `paths:` glob is too narrow
  to load when it's needed, so the structure is self-diagnosing.

## Writing

The authoring style in `workflow.md` applies, and applies hardest here: a living
doc is the easiest place to slip into narrating releases. "v0.14.8 made X
media-level" tells a reader nothing about what X does now and forces them to
replay every delta to find out.

## Compound-docs

Structure is in [compound-docs/TEMPLATE.md](../../compound-docs/TEMPLATE.md);
[INDEX.md](../../compound-docs/INDEX.md) lists what already exists — check it before
starting a new one, since extending the right doc beats a near-duplicate.

**On a long branch, keep a provisional doc as you go** — same filename convention,
`status: in progress`. Write down decisions, dead ends and gotchas while they are
fresh; a later session cannot reconstruct why an approach was abandoned.

Don't polish it. `/pr` **rewrites** it into the template's shape at PR time rather
than tidying it, precisely because the running commentary and per-session ordering
are what a future reader doesn't want. Verbose is fine; lost is not.

## Doc ownership

`/update-docs` owns the list of doc targets and the rules for each. Invoke the
skill rather than hand-editing docs.
