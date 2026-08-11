#!/usr/bin/env bash
# PreToolUse(Bash) gate for the two outward-facing actions:
#   git commit    — needs /ship (lint + review) against this exact content
#   gh pr create  — needs /pr (tests + ISO review + compound doc) on this tip
#
# Guidance in CLAUDE.md is advisory — an agent under context pressure can talk
# itself past it. This hook makes the ordinary commit shapes go through /ship
# instead. It is a speed bump, not a boundary, and the difference decides what
# may be relied on:
#
#   - It sees only Claude's own tool calls. A terminal commit is unaffected.
#   - It reads the tree as it stands WHEN THE HOOK FIRES, so whatever the same
#     command mutates first is invisible to it: `echo x >> f && git commit -a`
#     commits content no /ship ever saw. No amount of state inspection fixes
#     that — the hook runs before the mutation — so it would take refusing any
#     commit chained after a content-mutating segment.
#   - The parser resolves `git` in first position only. A shell keyword, wrapper
#     or env prefix (`if true; then git commit`, `time git commit`,
#     `GIT_EDITOR=true git commit`) is not recognised as a commit.
#
# So: real protection against drift under context pressure, which is the actual
# threat here, and no protection at all against someone stepping around it.
#
# Every defect found in this gate so far has been fail-*open*, and that asymmetry
# should drive any change to it. A gate that wrongly blocks is noticed in
# seconds; one that wrongly allows is invisible and looks healthy. When editing,
# ask of each branch: "if this goes wrong, does a commit get through unreviewed?"
#
# No `set -e`, deliberately: the gate must survive a failing probe and reach its
# own decision rather than dying half-way, because a non-zero exit here is an
# error the harness reports, not a denial.
set -uo pipefail

# Added *.md bytes above which a doc-only commit still needs review.
# Bytes, not lines: this repo writes 2000-char single-line paragraphs, so line
# counts say nothing. ~800 is 5-6 sentences of that prose. Counting *added*
# bytes means a large deletion never trips the gate — removing text cannot
# introduce the redundancy this check exists to catch.
# Measured under LC_ALL=C so it stays bytes everywhere: BSD awk's length()
# counts bytes while gawk in a UTF-8 locale counts characters, and this repo's
# prose is em-dash heavy enough for the two to disagree by a third.
DOC_CHAR_THRESHOLD=800

# svelte-check emits several lines per file; ruff emits one per finding and is
# already terse.
BUN_CHECK_TAIL=30

hook_dir=$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)

# Fail closed on missing tooling. Without these the gate cannot reach a verdict,
# and "cannot verify" must never read as "verified" — exit 2 blocks the call
# without needing any of them. jq is listed because emit_deny needs it too, so a
# missing jq would allow everything AND be unable to report that it had.
for tool in jq git sed awk paste; do
  command -v "$tool" >/dev/null || {
    echo "review-gate: $tool not found — refusing to allow unverified." >&2
    exit 2
  }
done

# shellcheck source=lib/state.sh
. "$hook_dir/lib/state.sh" || { echo "review-gate: cannot load lib/state.sh." >&2; exit 2; }

payload=$(cat)

emit_allow_note() { jq -n --arg c "$1" '{systemMessage:$c}'; exit 0; }
emit_deny() {
  jq -n --arg r "$1" '{hookSpecificOutput:{hookEventName:"PreToolUse",permissionDecision:"deny",permissionDecisionReason:$r}}'
  exit 0
}

cmd=$(jq -r '.tool_input.command // ""' <<<"$payload")

# Schema drift is a permanent silent disarm: if the Bash tool's input shape ever
# changes, the extraction yields "" and every branch below no-ops forever with no
# signal. So an unreadable command that *looks* like a gated action fails closed.
if [[ -z "$cmd" ]]; then
  [[ "$payload" == *commit* || "$payload" == *"pr"*"create"* ]] &&
    emit_deny "review-gate: could not read the command from the hook payload — refusing to allow unverified."
  exit 0
fi

# This hook runs on EVERY Bash call, so the common path must be nearly free.
# Tested against the *command*, never the whole payload: the payload carries
# transcript_path, which contains ".claude/projects/", so a payload-level `pr`
# test matches unconditionally and the guard degenerates to "contains create".
[[ "$cmd" == *commit* || "$cmd" == *"pr"*"create"* ]] || exit 0

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

repo_root=$(git rev-parse --show-toplevel 2>/dev/null) || {
  # Outside a repo there is nothing to gate, but a *failing* git is a different
  # thing from "not a repo" and used to be indistinguishable here — both exited 0.
  git rev-parse --is-inside-work-tree >/dev/null 2>&1 &&
    { echo "review-gate: cannot resolve the repo root." >&2; exit 2; }
  exit 0
}

# ------------------------------------------------------------------ PR gate
# `gh pr create` is the other outward-facing action worth gating. Plain
# `git push` deliberately is not: pushing a branch to back it up is routine,
# and the ask-first rule already covers pushing on the user's behalf.
if grep -Eq '^[[:space:]]*gh[[:space:]]+pr[[:space:]]+create([[:space:]]|$)' <<<"$segments"; then
  marker=$(pr_marker)
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

cd "$repo_root" || { echo "review-gate: cannot enter the repo root." >&2; exit 2; }

# What this commit could carry: the index UNION everything uncommitted in the
# worktree.
#
# Deliberately not "whichever one git will actually use". Which source git takes
# depends on flags this hook cannot reliably parse — a pathspec
# (`git commit -m x path/f.py` commits the worktree copy whatever the index
# holds), `-i`/`-o`/`--only`, `-a` in any glued spelling including `-am"msg"`,
# `git stage` as a synonym for add, or a chained `git add` that has not run yet
# because the hook fires first. Every attempt to detect those has missed a form,
# and each miss is a silent allow. The union needs no detection: it is a superset
# of every variant, and mark-reviewed.sh stamps the same union, so after a real
# /ship the two match exactly.
#
# The cost is strictness — an unreviewed edit to a file you are *not* committing
# also denies. That is the intended direction: this gate's every historical
# defect has been fail-open, and /ship covers the whole block anyway.
index_pairs() {
  if git rev-parse --verify -q HEAD >/dev/null; then
    # Plumbing, so it ignores diff.renames and never emits the two-path R form.
    git -c core.quotePath=false diff-index --cached --diff-filter=ACMRT HEAD |
      awk -F'\t' '{split($1,f," "); print f[4], $NF}'
  else
    git -c core.quotePath=false ls-files -s |
      awk -F'\t' '{split($1,f," "); print f[2], $NF}'
  fi
}

fingerprint_failed=0
worktree_pairs=$(uncommitted_paths | hash_paths) || fingerprint_failed=1
staged_pairs=$(index_pairs) || fingerprint_failed=1

# Checked here, ahead of the empty-set exit below, because the two are otherwise
# indistinguishable and the wrong one wins. hash_paths is all-or-nothing: a
# single unhashable path — a dangling symlink, a nested repo, an unreadable
# file, a dirty submodule gitlink — makes it emit nothing, and a corrupt index
# does the same to the staged half. Both then look exactly like "no files to
# check", which exits 0 and lets everything else in the tree ride along.
if (( fingerprint_failed )); then
  emit_deny "review-gate: could not fingerprint the working tree, so nothing can be verified."$'\n'"Usually a dangling symlink, an unreadable file, a nested git repo or a dirty submodule. Remove or fix it, then re-run /ship."$'\n\n'"Bypass for a genuinely trivial change: GATE_BYPASS=1 git commit ..."
fi

pairs=$(printf '%s\n%s\n' "$staged_pairs" "$worktree_pairs" | sed '/^$/d' | sort -u)
deleted=$(deleted_pairs)

# Deletions count toward *whether* review is required even though they carry no
# content to hash. Filtering them out of both let a pure-deletion change set —
# dropping a module, a migration, a whole doc tree — produce an empty file list
# and exit before any marker check.
verify=$( { printf '%s\n' "$pairs"; printf '%s\n' "$deleted"; } |
  grep -v '^$' | sort -u )
touched=$(cut -d' ' -f2- <<<"$verify" | grep -v '^$' | sort -u)
[[ -z "$touched" ]] && exit 0

fail=""
notes=""

# ------------------------------------------------------------- review pipeline
# Checked BEFORE lint: this costs milliseconds and lint costs seconds, and the
# remedy for a stale marker is /ship, which lints anyway.
if grep -qvE '\.md$' <<<"$touched"; then
  review_required=1                       # any real code
else
  # Added bytes across BOTH scopes, plus untracked docs in full. A brand-new
  # .md appears in no diff at all, so measuring only diffs scored a 20,000-byte
  # new document as 0 and waved it through — the exact shape of a compound doc.
  doc_chars=$( { git diff HEAD -- '*.md' 2>/dev/null
                 git diff --cached -- '*.md' 2>/dev/null
               } | LC_ALL=C awk '/^\+/ && !/^\+\+\+/ {n += length($0)} END {print n+0}')
  while IFS= read -r f; do
    [[ -n "$f" && -f "$f" ]] || continue
    doc_chars=$(( doc_chars + $(LC_ALL=C wc -c < "$f") ))
  done <<<"$(git -c core.quotePath=false ls-files --others --exclude-standard -- '*.md')"
  if (( doc_chars >= DOC_CHAR_THRESHOLD )); then
    review_required=1                     # prose large enough to hide bloat
  else
    review_required=0                     # a small doc fix reviews itself
  fi
fi

if (( review_required )); then
  marker=$(reviewed_marker)
  if [[ ! -s "$marker" ]]; then
    fail+="/ship has not run for this working tree."$'\n'
  elif [[ -z "$verify" ]]; then
    # hash_paths prints nothing on either failure path, so an empty set here
    # means the fingerprinting broke, not that there is nothing to check.
    fail+="Could not fingerprint what this commit contains — review not verified."$'\n'
  else
    # Every "<sha> <path>" (or "- <path>" for a deletion) the commit carries must
    # be one /ship signed off on. Comparing pairs rather than bare hashes is what
    # stops a new or renamed path validating against an unrelated file's content.
    while IFS= read -r pair; do
      [[ -n "$pair" ]] || continue
      # `--` is load-bearing: a deletion line begins "- ", which grep otherwise
      # parses as an option and errors on, denying every deletion forever.
      grep -qxF -- "$pair" "$marker" || {
        fail+="Files have changed since /ship last reviewed them."$'\n'; break; }
    done <<<"$verify"
  fi
  [[ -n "$fail" ]] && fail+="Run /ship (update-docs -> simplify -> lint), then commit."$'\n\n'
fi

# ---------------------------------------------------------------------- lint
# Whole-tree, matching exactly what CI runs — a staged-file subset can pass here
# and still fail CI. Also cheaper than scoping: ruff over the backend is ~26ms.
if [[ -z "$fail" ]] && grep -qE '^phsar/.*\.py$' <<<"$touched"; then
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

# Scoped to the extensions svelte-check actually reads, unlike the ruff branch's
# whole-tree run: this costs ~11s, not ~26ms, and a docs-only commit under
# phsar/frontend/ paid it in full to check nothing.
if [[ -z "$fail" ]] && grep -qE '^phsar/frontend/.*\.(svelte|ts|js|json)$' <<<"$touched"; then
  if command -v bun >/dev/null; then
    # Bounded, because a hook that outruns its own timeout is treated as
    # non-blocking — an unbounded check fails open on exactly the slowest path.
    # 180 must stay under the `timeout` on this hook in settings.json (240s):
    # past that the harness cancels the hook and the commit proceeds unverified.
    # timeout(1) is not on stock macOS, only via Homebrew coreutils, so its
    # absence is announced rather than silently reinstating the unbounded run.
    if command -v timeout >/dev/null; then
      out=$(cd phsar/frontend && timeout 180 bun run check 2>&1); rc=$?
    else
      notes+="review-gate: timeout(1) not on PATH — svelte-check ran unbounded, so a hang fails this gate open (brew install coreutils). "
      out=$(cd phsar/frontend && bun run check 2>&1); rc=$?
    fi
    if (( rc == 124 )); then          # timeout(1)'s deadline exit code
      fail+="svelte-check timed out — could not verify."$'\n\n'
    elif (( rc != 0 )); then
      fail+="bun run check failed:"$'\n'"$(tail -"$BUN_CHECK_TAIL" <<<"$out")"$'\n\n'
    fi
  else
    notes+="review-gate: bun not on PATH — svelte-check NOT verified. "
  fi
fi

[[ -n "$fail" ]] && emit_deny "${fail}Bypass for a genuinely trivial change: GATE_BYPASS=1 git commit ..."
[[ -n "$notes" ]] && emit_allow_note "$notes"
exit 0
