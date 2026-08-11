#!/usr/bin/env bash
# Records that /pr has reviewed the branch as it currently stands.
#
# Called as the LAST step of /pr, after the compound doc is committed — /pr
# creates commits of its own (review fixes, the compound doc), so a marker
# written earlier would vouch for a branch tip that did not exist yet.
#
# Stores the tip SHA rather than a timestamp: the question review-gate.sh asks
# is "was THIS branch state reviewed", and any commit after the marker changes
# the SHA. A timestamp would also be invalidated by a rebase that changed
# nothing.
set -euo pipefail

hook_dir=$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)
# shellcheck source=lib/state.sh
. "$hook_dir/lib/state.sh"

# Resolved before stamping: on an unborn HEAD `git rev-parse HEAD` exits 128 but
# still prints the literal string "HEAD" on stdout, and the gate recomputes the
# same string — so a marker written from a failed run compares equal and waves
# the PR through.
head_sha=$(git rev-parse --verify HEAD) || {
  echo "No commits on this branch yet — nothing to mark as PR-reviewed." >&2
  exit 1
}

printf '%s\n' "$head_sha" | stamp_marker "$(pr_marker)"
echo "PR marker stamped at $(git rev-parse --short HEAD)."
