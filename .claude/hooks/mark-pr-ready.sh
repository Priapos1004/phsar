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

repo_root=$(git rev-parse --show-toplevel)
state_dir="$repo_root/.claude/.state"
mkdir -p "$state_dir"
git rev-parse HEAD > "$state_dir/pr-ok"
echo "PR marker stamped at $(git rev-parse --short HEAD)."
