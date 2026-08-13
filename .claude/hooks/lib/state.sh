#!/usr/bin/env bash
# Shared marker contract for review-gate.sh and the two stampers.
#
# The writer and the reader have to agree byte-for-byte on how a file is
# fingerprinted, and on where the marker lives. Implemented separately they
# drift, and the failure is nasty: the gate reports "files have changed since
# /ship last reviewed them" on a tree that was just shipped, and the remedy it
# names re-stamps with the *other* convention and fails again. One definition,
# sourced by all three.
#
# `core.quotePath=false` on every path-listing command, not just some: git
# C-quotes non-ASCII names by default, so a mixed set makes an ümlaut path hash
# under one spelling and verify under another, denying that file forever.
#
# Blank lines are dropped with `sed '/^$/d'`, never `grep -v '^$'`. grep exits 1
# when nothing matches, and under the callers' `set -e` + `pipefail` an empty
# result is a perfectly normal state that would abort the pipeline mid-way —
# which is how a deletion-only /ship silently wrote an empty marker.

state_dir()       { printf '%s/.claude/.state' "$(git rev-parse --show-toplevel)"; }
reviewed_marker() { printf '%s/reviewed-ok' "$(state_dir)"; }
pr_marker()       { printf '%s/pr-ok' "$(state_dir)"; }

# Marker lines are "<blob-sha> <path>" for content and "- <path>" for a
# deletion, sorted.
#
# The path is carried, not just the hash. A bare hash set lets any brand-new or
# renamed file validate against some unrelated file's reviewed content — and an
# empty new file passes permanently, since the empty blob enters the marker the
# first time /ship ever runs over one.
#
# Prints nothing on any failure, so callers test for empty output rather than
# needing a distinct sentinel.
hash_paths() {
  local paths hashes
  paths=$(sed '/^$/d')
  [[ -n "$paths" ]] || return 0

  # One spawn regardless of file count: ~42ms for the whole 647-file tree, where
  # a per-file loop would be one process each.
  hashes=$(printf '%s\n' "$paths" |
    git -c core.quotePath=false hash-object --stdin-paths 2>/dev/null) || return 1

  # A short read means hashing failed somewhere. Emitting the misaligned pairs
  # would silently attribute one file's hash to another's path, so refuse.
  [[ "$(grep -c . <<<"$paths")" -eq "$(grep -c . <<<"$hashes")" ]] || return 1

  paste -d' ' <(printf '%s\n' "$hashes") <(printf '%s\n' "$paths") | sort
}

# The tracked-plus-staged pair both callers need, over one --diff-filter.
# `git diff HEAD` fatals on an unborn HEAD, hence the guard.
_changed_with_filter() {
  git -c core.quotePath=false diff HEAD --name-only --diff-filter="$1" 2>/dev/null || true
  git -c core.quotePath=false diff --cached --name-only --diff-filter="$1" 2>/dev/null || true
}

# Everything uncommitted that still has content to hash. T (type change, e.g. a
# file swapped for a symlink) is in the set: it is neither an ordinary
# modification nor a deletion, and omitting it left such a change in no set at
# all, which read as "nothing to review".
uncommitted_paths() {
  { _changed_with_filter ACMRT
    git -c core.quotePath=false ls-files --others --exclude-standard
  } | sed '/^$/d' | sort -u
}

# Deletions carry no content, so they are tracked as their own marker shape
# rather than dropped. Dropping them meant a pure-deletion change set produced
# an empty file list and skipped the marker check entirely.
deleted_paths() { _changed_with_filter D | sed '/^$/d' | sort -u; }

# "- <path>" lines for the deletion half of a marker.
deleted_pairs() { deleted_paths | sed 's/^/- /' | sort; }

# Write a marker whole. A direct `>` truncates before the write, so a failure
# part-way leaves an empty file — which the gate reads as "never ran" while the
# stamper reports success.
stamp_marker() {
  local dest="$1" dir tmp
  dir=$(dirname "$dest"); mkdir -p "$dir"
  tmp=$(mktemp "$dir/.stamp.XXXXXX") || return 1
  cat > "$tmp"
  mv "$tmp" "$dest"
}
