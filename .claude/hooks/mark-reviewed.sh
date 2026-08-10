#!/usr/bin/env bash
# Records which file contents /ship has reviewed, for review-gate.sh.
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
# excluded (ACMR) — there is no content left to hash. `git diff HEAD` fatals on
# an unborn HEAD, so that case falls back to untracked files alone.
changed=$(
  { git diff HEAD --name-only --diff-filter=ACMR 2>/dev/null || true
    git ls-files --others --exclude-standard
  } | sort -u
)

# Written via a temp file and moved into place: a direct `>` truncates the
# marker before the write, so a failure part-way leaves it empty — which the
# gate reads as "/ship never ran" while this script reports success.
tmp=$(mktemp "$state_dir/.reviewed-ok.XXXXXX")
trap 'rm -f "$tmp"' EXIT
printf '%s\n' "$changed" | grep -c . >/dev/null && \
  printf '%s\n' "$changed" | git -c core.quotePath=false hash-object --stdin-paths > "$tmp"
mv "$tmp" "$state_dir/reviewed-ok"
trap - EXIT

count=$(grep -c . < "$state_dir/reviewed-ok" || true)
if [[ "$count" -eq 0 ]]; then
  echo "Nothing uncommitted to record — /ship has no changes to vouch for." >&2
  exit 1
fi
echo "Reviewed $count file(s) recorded."
