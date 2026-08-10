#!/usr/bin/env bash
# PreToolUse(Bash) gate for the two outward-facing actions:
#   git commit    — needs /ship (lint + review) against this exact content
#   gh pr create  — needs /pr (tests + ISO review + compound doc) on this tip
#
# Guidance in CLAUDE.md is advisory — an agent under context pressure can talk
# itself past it. This hook cannot be talked past, which is the whole point.
# It only sees Claude's tool calls; anything typed in a terminal is unaffected.
set -uo pipefail

# Added *.md characters above which a doc-only commit still needs review.
# Characters, not lines: this repo writes 2000-char single-line paragraphs, so
# line counts say nothing. ~800 is 5-6 sentences of that prose. Counting *added*
# characters means a large deletion never trips the gate — removing text cannot
# introduce the redundancy this check exists to catch.
DOC_CHAR_THRESHOLD=800

# jq is the one dependency the gate cannot work without — emit_deny needs it too,
# so a missing jq would allow everything AND be unable to say so. Exit 2 blocks
# the call without needing jq at all: fail closed, and loudly.
command -v jq >/dev/null || {
  echo "review-gate: jq not found — refusing to allow unverified." >&2
  exit 2
}

payload=$(cat)

# This hook runs on EVERY Bash call, so the common path must be nearly free.
# Pure-bash substring tests cost no process; jq and git run only for payloads
# that could possibly be a gated action. Deliberately a superset — the exact
# checks are below. Both terms are needed: a `gh pr create` payload contains no
# "commit", and `pr*create` rather than the literal phrase so that any spacing
# between the words still reaches the gate.
[[ "$payload" == *commit* || "$payload" == *pr*create* ]] || exit 0

cmd=$(jq -r '.tool_input.command // ""' <<<"$payload")

emit_allow_note() { jq -n --arg c "$1" '{systemMessage:$c}'; exit 0; }
emit_deny() {
  jq -n --arg r "$1" '{hookSpecificOutput:{hookEventName:"PreToolUse",permissionDecision:"deny",permissionDecisionReason:$r}}'
  exit 0
}

# Deliberate, logged escape hatch. Anchored as a leading env assignment so that
# merely *mentioning* it in a commit message cannot silently disable the gate.
if [[ "$cmd" =~ ^[[:space:]]*GATE_BYPASS=1[[:space:]] ]]; then
  emit_allow_note "review-gate: BYPASSED via GATE_BYPASS=1."
fi

# Command positions only: the start of the string, or just after a shell
# separator. Everything gated below is matched against THESE segments, never the
# raw string — otherwise any command that merely mentions `git commit` or
# `gh pr create` (an echo, a heredoc writing docs, a test harness) gets blocked.
segments=$(printf '%s' "$cmd" | sed -E 's/(\|\||&&|[;&|()]|\$\()/\n/g')

repo_root=$(git rev-parse --show-toplevel 2>/dev/null) || exit 0

# ------------------------------------------------------------------ PR gate
# `gh pr create` is the other outward-facing action worth gating. Plain
# `git push` deliberately is not: pushing a branch to back it up is routine,
# and the ask-first rule already covers pushing on the user's behalf.
if grep -Eq '^[[:space:]]*gh[[:space:]]+pr[[:space:]]+create([[:space:]]|$)' <<<"$segments"; then
  marker="$repo_root/.claude/.state/pr-ok"
  head_sha=$(git rev-parse HEAD 2>/dev/null)
  bypass_hint=$'\n\n'"Bypass for a genuinely trivial change: GATE_BYPASS=1 gh pr create ..."
  if [[ ! -s "$marker" ]]; then
    emit_deny "/pr has not run on this branch."$'\n'"Run /pr (tests -> ISO review -> compound doc), then open the PR.${bypass_hint}"
  fi
  if [[ "$(cat "$marker")" != "$head_sha" ]]; then
    emit_deny "Commits have landed since /pr last reviewed this branch."$'\n'"Re-run /pr so the review and the compound doc cover what will merge.${bypass_hint}"
  fi
  # No exit: a chained `git commit ... && gh pr create` must clear both gates.
fi

# --------------------------------------------------------------- commit gate
# One subcommand per `git` occurrence, taken per segment. `break` rather than
# `exit` matters: exiting on the first match let `git add -A && git commit`
# resolve to `add` and skip the gate entirely — the most common commit shape.
# Flag handling keeps `git -C dir commit` and `git -c k=v commit` working while
# `git log --grep commit` still resolves to `log`.
subcmds=$(awk '$1=="git"{for(j=2;j<=NF;j++){
  if($j ~ /^-/){ if($j=="-C"||$j=="-c") j++; continue } print $j; break }}' <<<"$segments")
grep -qxF commit <<<"$subcmds" || exit 0

cd "$repo_root" || exit 0

# `git commit -a` stages tracked edits at commit time, so the staged set is
# empty here and the real subject of the commit is the unstaged diff. Both the
# file list and the doc-size measurement below must read from the same place.
# HEAD rather than an empty array: bash 3.2 (macOS) treats "${arr[@]}" on an
# empty array as unbound under `set -u`, which silently zeroed the measurement
# and let arbitrarily large doc-only `-a` commits skip review.
staged=$(git diff --cached --name-only --diff-filter=ACMR)
diff_scope=(--cached)
if [[ -z "$staged" ]]; then
  staged=$(git diff --name-only --diff-filter=ACMR)
  diff_scope=(HEAD)
fi
[[ -z "$staged" ]] && exit 0

fail=""
notes=""

# ------------------------------------------------------------- review pipeline
# Checked BEFORE lint: this costs milliseconds and lint costs ~8s, and the
# remedy for a stale marker is /ship, which lints anyway.
if grep -qvE '\.md$' <<<"$staged"; then
  review_required=1                       # any real code
elif (( $(git diff "${diff_scope[@]}" -- '*.md' |
          awk '/^\+/ && !/^\+\+\+/ {n += length($0)} END {print n+0}') >= DOC_CHAR_THRESHOLD )); then
  review_required=1                       # prose large enough to hide bloat
else
  review_required=0                       # a small doc fix reviews itself
fi

if (( review_required )); then
  marker="$repo_root/.claude/.state/reviewed-ok"
  if [[ ! -s "$marker" ]]; then
    fail+="/ship has not run for this working tree."$'\n'
  else
    # Every staged file's current content must be one /ship signed off on.
    hashes=$(printf '%s\n' "$staged" | git -c core.quotePath=false hash-object --stdin-paths 2>/dev/null) || hashes=""
    if [[ $(grep -c . <<<"$hashes") -ne $(grep -c . <<<"$staged") ]]; then
      # Fewer hashes than files means hashing failed somewhere. Treating that as
      # "verified" would allow the commit on no evidence at all.
      fail+="Could not hash every staged file — review not verified."$'\n'
    else
      while IFS= read -r h; do
        [[ -n "$h" ]] || continue
        grep -qxF "$h" "$marker" || { fail+="Files have changed since /ship last reviewed them."$'\n'; break; }
      done <<<"$hashes"
    fi
  fi
  [[ -n "$fail" ]] && fail+="Run /ship (update-docs -> simplify -> lint), then commit."$'\n\n'
fi

# ---------------------------------------------------------------------- lint
# Whole-tree, matching exactly what CI runs — a staged-file subset can pass here
# and still fail CI. Also cheaper than scoping: ruff over the backend is ~26ms.
if [[ -z "$fail" ]] && grep -qE '^phsar/.*\.py$' <<<"$staged"; then
  if command -v ruff >/dev/null; then
    if ! out=$(cd phsar && ruff check . 2>&1); then
      fail+="ruff check failed:"$'\n'"$out"$'\n\n'"Auto-fix what it can: cd phsar && ruff check . --fix"$'\n\n'
    fi
  else
    # Missing tooling is an environment problem, not a quality problem, so it
    # warns and allows rather than blocking a legitimate commit.
    notes+="review-gate: ruff not on PATH — Python lint NOT verified. "
  fi
fi

if [[ -z "$fail" ]] && grep -qE '^phsar/frontend/' <<<"$staged"; then
  if command -v bun >/dev/null; then
    if ! out=$(cd phsar/frontend && bun run check 2>&1); then
      fail+="bun run check failed:"$'\n'"$(tail -30 <<<"$out")"$'\n\n'
    fi
  else
    notes+="review-gate: bun not on PATH — svelte-check NOT verified. "
  fi
fi

[[ -n "$fail" ]] && emit_deny "${fail}Bypass for a genuinely trivial change: GATE_BYPASS=1 git commit ..."
[[ -n "$notes" ]] && emit_allow_note "$notes"
exit 0
