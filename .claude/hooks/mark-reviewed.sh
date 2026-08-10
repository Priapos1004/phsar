#!/usr/bin/env bash
# Records which file contents /ship has reviewed, for pre-commit-gate.sh.
#
# Called as the LAST step of /ship, never on its own: /update-docs and /simplify
# both edit files, so a marker written at the start of the pipeline would vouch
# for work done after it.
#
# Content hashes, not timestamps. mtime is wrong in both directions — `git stash
# pop`, a branch round-trip and any rebase all rewrite byte-identical files with
# fresh mtimes, which would force a re-run of a pipeline whose steps are
# minutes-long review passes; and second-granularity timestamps let an edit made
# within the same second as the stamp pass unreviewed. A blob hash answers the
# question actually being asked: was *this content* reviewed.
set -euo pipefail

repo_root=$(git rev-parse --show-toplevel)
state_dir="$repo_root/.claude/.state"
mkdir -p "$state_dir"
cd "$repo_root"

# Everything uncommitted: tracked edits plus untracked files. Deletions are
# excluded (ACMR) — there is no content left to hash.
{
  git diff HEAD --name-only --diff-filter=ACMR
  git ls-files --others --exclude-standard
} | sort -u | git hash-object --stdin-paths > "$state_dir/reviewed-ok" 2>/dev/null || true

echo "Reviewed $(wc -l < "$state_dir/reviewed-ok" | tr -d ' ') file(s) recorded."
