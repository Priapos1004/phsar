---
name: galaxy-names
description: Name the galaxy map's sectors and regions on the deployed app after a refit — review every group against its members with subagents, agree the renames with the user, apply them through the admin API and record them in names.md. Use after any galaxy_rebuild (the quarterly refit or any other), or whenever the user wants the map's names reviewed.
---

# Name the galaxy map

After a refit some groups show the fit's auto labels, and a carried hand name can land on
a group whose members changed ([galaxy](../../../docs/features/galaxy.md#names) says which
names carry). This pass reviews every group and fixes both. The rules a name follows are
[conventions.md](conventions.md); the names in use, with the anchors that identify each
group, are [names.md](names.md).

Run the script from the repo root with `.venv/bin/python`. It logs in with the admin
credentials in `phsar/.env`.

## Steps

1. **Get the deployed API's base URL** — from memory or the user. It is never written into
   the repo ([workflow.md](../../rules/workflow.md), "Never commit the deployed URL").
2. **Fetch** into a scratch directory:
   `.venv/bin/python .claude/skills/galaxy-names/galaxy_names.py fetch --api <url> --out <dir>`.
3. **Review with subagents**, one per slice of sectors (about 600–800 stars each), in
   parallel. Each reads `digest.md` whole — every group's name and profile, and the names
   the rebuild dropped — plus its own sectors' files, `conventions.md` and `names.md`. A
   group whose name is not in `names.md` shows the fit's auto label. Each reports per
   group: KEEP, RENAME or GRAB-BAG; a proposal and one alternative; 3–4 anchors; one line
   of why; and any strikingly mis-clustered members. Tell each which sectors the others
   cover. Read-only: they never call the API.
4. **Consolidate.** Run the conventions over every proposal together rather than per
   slice, and take a reviewer's alternative where it clears a clash. Present only the
   changes, one table, and agree them with the user; they routinely change a few.
5. **Apply.** Write the agreed renames as `{"S7": "…", "R23": "…"}` (null clears a hand
   name back to the auto label) and run
   `.venv/bin/python .claude/skills/galaxy-names/galaxy_names.py apply --api <url> --out <dir> <renames.json>`.
6. **Record.** Rewrite [names.md](names.md) whole from the final map — every group, its
   stars, name, anchors and why, the fit date at the top — and `/ship` it, the commit
   message saying what the pass changed. A rule the pass settled goes into
   [conventions.md](conventions.md) in the same commit.
