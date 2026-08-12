---
description: How to write a rule or an agent rubric — frontmatter, glob forms, and how to verify either one actually loads.
paths: ".claude/{rules,agents}/**/*.md"
---

# Writing a rule or a rubric

Both are markdown with YAML frontmatter, and both fail the same way: silently, by
never being loaded at all. **Verifying that is the part that matters**, and the
method at the bottom applies to either.

## Rules

A rule loads at startup without `paths:`; with `paths:` it loads only once a
matching file enters context, which is what keeps the always-loaded budget small.

Keep rules to **invariants and their constraints**. Background, rationale and
history belong in `compound-docs/`; a rule is read while someone is mid-edit.

## `paths:` accepts globs, brace sets, lists and single files

Measured on CLI 2.1.128 — every form in the table loads. Braces expanding mid-path
is the only non-obvious one, including when an alternative contains a `/`.

| Form | |
|---|---|
| `"phsar/app/daos/**/*.py"` | ✅ |
| `"phsar/{app,tests,scripts}/**/*.py"` — braces expand | ✅ |
| `"phsar/{app/models,app/daos}/**/*.py"` — alternatives spanning a `/` | ✅ |
| `"**/*.md"` — matches inside dot-directories too | ✅ |
| `"phsar/app/daos/**"` — no trailing `/*` | ✅ |
| `"phsar/app/daos/base_dao.py"` — one named file | ✅ |
| a YAML **list** of any of the above | ✅ |

**Only these forms, only this CLI version.** Nothing here says an untested form
works, and a narrower future release would break a rule *silently* — it would
match nothing, load never, and report neither. Re-verify after an upgrade, and
treat the load test below as the only real protection.

Prefer a **directory-shaped** glob over a **content-shaped** one. Scoping to a
subtree means a file nobody has written yet already matches; scoping to the files
that currently exhibit a pattern means the rule loads where the convention is kept
and stays silent in the new file about to break it. Every rule here is
directory-shaped for that reason.

## Agent rubrics

A file in `.claude/agents/` is the rubric one reviewer applies — what it looks
for, what it must cite, and what it must **not** flag. Put the calibration in the
rubric, never in the prompt that launches it: a skill that summarises a rubric
re-summarises it differently every run, and the nuanced parts go first.

**These files do not register as agent types.** A skill loads one by telling a
general search agent to *read the file and apply it*; naming it as a
`subagent_type` is a runtime "Agent type not found". So the frontmatter is
intent rather than configuration — a rubric's `tools:` does not restrict
anything, and a rubric that must not edit has to say so in its body.

Check what actually resolves before wiring a skill to a name:

```
claude -p --model haiku "List ONLY the subagent_type values available to the Agent tool" < /dev/null
```

## Verify it actually loads

Never assume it did. In a fresh headless session — `< /dev/null` because the
nested CLI otherwise blocks on inherited stdin and reads as a hung check:

```
claude -p --model haiku "<question only this file can answer>" < /dev/null
```

Two arms: without touching a matching file (expect the answer absent), then after
reading one (expect it present). Pick a fact that appears in **no** other loaded
doc, or a correct answer proves nothing: root `CLAUDE.md` is always in context and
covers most of this codebase. Beware a fact the model can simply *infer* — its own
tool list and environment answer more than they look like they do.

Ask for what is "already in your context". **Do not** phrase the arm as a
prohibition ("don't read X"): that is honoured as a gag order on knowledge already
loaded, which manufactures the absent answer the test is hunting for.

**Repeat any absent answer before believing it** — including the first arm. A file
that does load can still come back empty once and pass on every retry, so a single
absence is not evidence either way.
