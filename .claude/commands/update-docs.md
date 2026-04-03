Update project documentation after code changes.

Review what changed in the current work session and update all affected documentation. Always read each file before editing. Present proposed changes to the user for approval before writing.

## Documentation Files

### 1. `CLAUDE.md` (root)
**Purpose:** Claude Code project instructions — architecture, commands, patterns, config, key conventions.
**When to update:** Structural/architectural changes (new layers, new routers, new services, changed dependency flow, new config keys, new commands, changed patterns).
**Be careful:**
- This is the primary onboarding doc for Claude Code — keep it accurate and concise.
- Don't bloat sections with implementation details; describe patterns, not individual functions.
- Update the "Architecture" subsections when new directories/layers are added.
- Update "Commands" when new scripts, CLI commands, or workflows are introduced.
- Update "Configuration" when new env vars are added.

### 2. `README.md` (root)
**Purpose:** High-level project overview, conda/docker setup, getting started pointers.
**When to update:** Changes to the setup process (new dependencies, docker config changes, new prerequisites).
**Be careful:**
- This is for first-time setup — keep instructions sequential and copy-pasteable.
- Don't duplicate content from `phsar/README.md`; this file points there for app-specific setup.

### 3. `phsar/README.md`
**Purpose:** Webapp-specific README — folder structure tree, env vars, alembic, running the app.
**When to update:** Files/directories added or removed, env var changes, new setup steps.
**Be careful:**
- **The folder structure tree must reflect the working state of the repo** — include files that exist when actively developing (`.env`, `claude related files`, `alembic/versions/*.py`, as a collapsed entry, etc.), not just what git tracks. This shows users what the repo looks like when everything is set up correctly.
- To regenerate the tree: inspect the actual directory structure, then manually compose the tree maintaining the existing style (collapse `ui/` subdirectories, collapse `alembic/versions/`, show key config files).
- Update env var documentation when new vars are added to `config.py`.
- Keep the alembic instructions current with any migration workflow changes.

### 4. `phsar/frontend/USER_FLOWS.md`
**Purpose:** User-facing behavior specification — serves as test spec for frontend behavior.
**When to update:** User-visible behavior changes (new routes, changed UI flows, new components that alter UX, modified API interactions from frontend).
**Be careful:**
- This is a test specification, not a feature wishlist — only document behavior that is currently implemented.
- Update route tables when routes are added/removed.
- Update API endpoint tables when the frontend starts using new endpoints.
- Update error states when error handling changes.
- Don't document backend-only changes that have no frontend impact.

### 5. `.claude/plans/agile-sprouting-gray.md`
**Purpose:** Feature design decisions and version roadmap — long-lived planning document.
**When to update:** Design decisions are made or changed, milestones are completed or rescheduled, scope of a feature changes, new features are planned.
**Be careful:**
- This is the source of truth for design decisions — accuracy matters.
- When a milestone is completed, mark it clearly (e.g., strikethrough or "✓ shipped in v0.X.0").
- When a decision changes, update the "Key Decisions" section for that feature — don't just append, replace the outdated decision.
- Keep the version roadmap table current with actual progress.
- When scope changes, update both the feature section AND the roadmap table.

### 6. GitHub Issues
**Purpose:** Track work items, bugs, and feature requests aligned with the roadmap.
**When to update:** Roadmap changes that affect planned work, milestones completed, scope changes that require new issues or closing outdated ones.
**Be careful:**
- Always check existing issues before creating duplicates (`gh issue list`).
- When closing issues, reference the relevant commit or PR.
- When roadmap versions shift, update milestone assignments on affected issues.
- **Always ask the user before creating, closing, or modifying issues.**

## Process

1. **Assess scope**: Determine which of the above files/systems are affected by the current changes.
2. **Read affected files**: Read each file that needs updating. Never edit blind.
3. **Draft changes**: For each file, identify what specifically needs to change and why.
4. **Present for approval**: Show the user a summary of proposed changes across all affected docs. For GitHub issues, list planned creates/updates/closes.
5. **Apply changes**: After user approval, make all edits.

## Arguments

$ARGUMENTS
