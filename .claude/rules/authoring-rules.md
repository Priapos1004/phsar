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

## `paths:` must be a single string ending in `**/*` or `**/*.ext`

Observed on CLI 2.1.128 — treat as version-specific and re-verify after an
upgrade rather than as documented mechanics.

| Form | |
|---|---|
| `"phsar/app/daos/**/*.py"` | ✅ |
| `"phsar/{app,tests,scripts}/**/*.py"` — braces expand | ✅ |
| `"**/*.md"` | ✅ |
| a YAML **list** of globs | ❌ never loads |
| `"phsar/app/daos/**"` — no trailing `/*` | ❌ matches nothing |

Both failing forms fail the **same silent way**: the rule matches nothing, so it
loads never, which is indistinguishable from the feature being unsupported. There
is no error either way.

## Verify a new rule actually loads

Never assume it did. In a fresh headless session:

```
claude -p --model haiku "<question only this rule can answer>"
```

Run it twice — once without touching a matching file (expect the rule's answer to
be absent), once after reading one (expect it present). Pick a fact that appears
in **no** other loaded doc, or a correct answer proves nothing: root `CLAUDE.md`
is always in context and covers most of this codebase.
