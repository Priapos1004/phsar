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
#
# The hash+path format and the file set both come from lib/state.sh, shared with
# the gate that reads this marker — see the header there for why.
set -euo pipefail

hook_dir=$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)
# shellcheck source=lib/state.sh
. "$hook_dir/lib/state.sh"

cd "$(git rev-parse --show-toplevel)"
marker=$(reviewed_marker)

# Hashing failure is reported, never swallowed. hash_paths is all-or-nothing, so
# one unhashable path yields an empty set that is indistinguishable from a clean
# tree — and stamping that would tell the gate a whole block had been reviewed.
content=$(uncommitted_paths | hash_paths) || {
  echo "Could not hash every uncommitted file — /ship cannot vouch for this tree." >&2
  echo "Usually a dangling symlink, an unreadable file, a nested git repo, or a" >&2
  echo "dirty submodule. Remove or fix it and re-run." >&2
  exit 1
}

# Deletions are recorded too, as "- <path>". Without them a change set that only
# removes files had nothing to stamp: the marker came out empty, which the gate
# reads as "/ship never ran", and no amount of re-running could clear it.
records=$(printf '%s\n%s\n' "$content" "$(deleted_pairs)" | sed '/^$/d' | sort -u)

# Built in full before anything is written, so a clean tree or a failure leaves
# the previous marker intact rather than truncating it and reporting nothing.
if [[ -z "$records" ]]; then
  echo "Nothing uncommitted to record — /ship has no changes to vouch for." >&2
  exit 1
fi

printf '%s\n' "$records" | stamp_marker "$marker"
echo "Reviewed $(grep -c . <<<"$records") path(s) recorded."
