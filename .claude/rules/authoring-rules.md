---
description: How to write a rule file in this directory — frontmatter, glob forms, and how to verify one actually loads.
paths: ".claude/rules/**/*.md"
---

# Writing a rule

A rule file is markdown with YAML frontmatter. Without `paths:` it loads at
startup; with `paths:` it loads only once a matching file enters context, which
is what keeps the always-loaded budget small.

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

## Verify a new rule actually loads

Never assume it did. In a fresh headless session — `< /dev/null` because the
nested CLI otherwise blocks on inherited stdin and reads as a hung check:

```
claude -p --model haiku "<question only this rule can answer>" < /dev/null
```

Two arms: without touching a matching file (expect the rule's answer absent), then
after reading one (expect it present). Pick a fact that appears in **no** other
loaded doc, or a correct answer proves nothing: root `CLAUDE.md` is always in
context and covers most of this codebase.

**Repeat any absent answer before believing it** — including the first arm. A rule
that does load can still come back empty once and pass on every retry, so a single
absence is not evidence either way.
