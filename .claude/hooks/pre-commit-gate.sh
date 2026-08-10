#!/usr/bin/env bash
# PreToolUse(Bash) gate: nothing commits without lint and the review pipeline.
#
# Guidance in CLAUDE.md is advisory — an agent under context pressure can talk
# itself past it. This hook cannot be talked past, which is the whole point.
# It only sees Claude's tool calls; commits typed in a terminal are unaffected.
set -uo pipefail

# Added *.md characters above which a doc-only commit still needs review.
# Characters, not lines: this repo writes 2000-char single-line paragraphs, so
# line counts say nothing. ~800 is 5-6 sentences of that prose. Counting *added*
# characters means a large deletion never trips the gate — removing text cannot
# introduce the redundancy this check exists to catch.
DOC_CHAR_THRESHOLD=800

payload=$(cat)

# This hook runs on EVERY Bash call, so the common path must be nearly free.
# A pure-bash substring test costs no process; jq and git run only for payloads
# that could possibly be a commit. Deliberately a superset — the exact check is
# below, this just skips the 99% that cannot match.
[[ "$payload" == *commit* ]] || exit 0

cmd=$(jq -r '.tool_input.command // ""' <<<"$payload")

# The subcommand is the first non-flag word after `git`, so this matches
# `git -C dir commit` and `git -c k=v commit` while `git log --grep commit`
# correctly resolves to `log`.
subcmd=$(awk '{for(i=1;i<=NF;i++) if($i=="git"){for(j=i+1;j<=NF;j++){
  if($j ~ /^-/){ if($j=="-C"||$j=="-c") j++; continue } print $j; exit }}}' <<<"$cmd")
[[ "$subcmd" == "commit" ]] || exit 0

emit_allow_note() { jq -n --arg c "$1" '{systemMessage:$c}'; exit 0; }
emit_deny() {
  jq -n --arg r "$1" '{hookSpecificOutput:{hookEventName:"PreToolUse",permissionDecision:"deny",permissionDecisionReason:$r}}'
  exit 0
}

# Deliberate, logged escape hatch. Anchored as a leading env assignment so that
# merely *mentioning* it in a commit message cannot silently disable the gate.
if [[ "$cmd" =~ ^[[:space:]]*GATE_BYPASS=1[[:space:]] ]]; then
  emit_allow_note "pre-commit-gate: BYPASSED via GATE_BYPASS=1."
fi

repo_root=$(git rev-parse --show-toplevel 2>/dev/null) || exit 0
cd "$repo_root" || exit 0

# `git commit -a` stages tracked edits at commit time, so the staged set is
# empty here and the real subject of the commit is the unstaged diff. Both the
# file list and the doc-size measurement below must read from the same place.
staged=$(git diff --cached --name-only --diff-filter=ACMR)
diff_scope=(--cached)
if [[ -z "$staged" ]]; then
  staged=$(git diff --name-only --diff-filter=ACMR)
  diff_scope=()
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
    while IFS= read -r h; do
      [[ -n "$h" ]] || continue
      grep -qxF "$h" "$marker" || { fail+="Files have changed since /ship last reviewed them."$'\n'; break; }
    done < <(printf '%s\n' "$staged" | git hash-object --stdin-paths 2>/dev/null)
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
    notes+="pre-commit-gate: ruff not on PATH — Python lint NOT verified. "
  fi
fi

if [[ -z "$fail" ]] && grep -qE '^phsar/frontend/' <<<"$staged"; then
  if command -v bun >/dev/null; then
    if ! out=$(cd phsar/frontend && bun run check 2>&1); then
      fail+="bun run check failed:"$'\n'"$(tail -30 <<<"$out")"$'\n\n'
    fi
  else
    notes+="pre-commit-gate: bun not on PATH — svelte-check NOT verified. "
  fi
fi

[[ -n "$fail" ]] && emit_deny "${fail}Bypass for a genuinely trivial change: GATE_BYPASS=1 git commit ..."
[[ -n "$notes" ]] && emit_allow_note "$notes"
exit 0
