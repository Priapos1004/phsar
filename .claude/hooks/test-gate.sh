#!/usr/bin/env bash
# Regression tests for review-gate.sh. Run from anywhere: .claude/hooks/test-gate.sh
#
# Every defect ever found in the gate has been fail-*open*, and a fail-open gate
# looks perfectly healthy from the outside — there is no symptom to notice. That
# is why these exist: each case drives the real hook in a throwaway repo and
# asserts the verdict, so a hole cannot silently reopen under a later edit.
#
# Add a case for any new hole rather than only fixing it. A fix with no test is
# how the fixed hole comes back.
#
# DENY-LINT is distinguished from DENY on purpose: a ruff/svelte-check failure
# denying for unrelated reasons would otherwise mask a hole that had reopened.
set -uo pipefail

SRC="${1:-$(cd "$(dirname "${BASH_SOURCE[0]}")/../.." && pwd)}"
WORK=$(mktemp -d)
# Guard rather than trust: mktemp failing still assigns, so `set -u` says nothing
# and every `rm -rf "$WORK/r"` below would target "/r" instead.
[[ -n "$WORK" && -d "$WORK" ]] || { echo "test-gate: could not create a work dir." >&2; exit 1; }
trap 'rm -rf "$WORK"' EXIT

# The throwaway repos must not inherit the developer's git config. `commit.gpgsign`
# is the one that bites — every `git commit` below would block on pinentry or fail
# outright, reporting the wrong verdict for nearly every case. Since this suite is
# the ONLY symptom of a fail-open regression, a false red costs as much as a false
# green. `core.hooksPath` and `init.templateDir` would interfere the same way.
export GIT_CONFIG_GLOBAL=/dev/null GIT_CONFIG_SYSTEM=/dev/null

pass=0; fail=0
setup() {
  rm -rf "$WORK/r"; mkdir -p "$WORK/r"; cd "$WORK/r" || exit 1
  git init -q .; git config user.email t@t; git config user.name t
  mkdir -p .claude/hooks/lib phsar/app phsar/frontend/src
  cp "$SRC/.claude/hooks/review-gate.sh"   .claude/hooks/
  cp "$SRC/.claude/hooks/mark-reviewed.sh" .claude/hooks/
  cp "$SRC/.claude/hooks/mark-pr-ready.sh" .claude/hooks/
  cp "$SRC/.claude/hooks/lib/state.sh"     .claude/hooks/lib/
  chmod +x .claude/hooks/*.sh
  echo ".claude/.state/" > .gitignore
  echo "seed" > seed.txt
  git add -A >/dev/null; git commit -qm init
}
# One definition of the harness payload shape. review-gate.sh calls a schema
# change here "a permanent silent disarm", so every driver below must feed the
# same shape — two spellings means updating one and leaving the other asserting
# against a payload the hook no longer parses, while still reporting green.
payload_for() { printf '{"tool_name":"Bash","tool_input":{"command":%s}}' "$(printf '%s' "$1" | jq -Rs .)"; }

run() {  # run <command-string> -> "DENY" (review) | "DENY-LINT" | "ALLOW"
  local out
  out=$(payload_for "$1" | ./.claude/hooks/review-gate.sh 2>/dev/null)
  # jq -n pretty-prints, so the key and value are separated by ": " — match loosely.
  if grep -Eq '"permissionDecision"[[:space:]]*:[[:space:]]*"deny"' <<<"$out"; then
    # A lint or PR denial must not be reported as a review denial: either would
    # mask a still-open hole behind an unrelated red.
    if grep -q 'ruff check failed\|bun run check failed\|svelte-check timed out' <<<"$out"
    then echo DENY-LINT
    elif grep -q '/pr has not run\|since /pr last reviewed' <<<"$out"
    then echo DENY-PR
    else echo DENY; fi
  else echo ALLOW; fi
}
check() { # check <label> <expected> <actual>
  # Arity guard: a missing space before the expected verdict silently glues it to
  # the label, and the resulting failure points nowhere near the real mistake.
  if [[ $# -ne 3 ]]; then
    fail=$((fail+1)); printf '  FAIL malformed check (%d args): %s\n' "$#" "${1:-}"; return
  fi
  if [[ "$2" == "$3" ]]; then pass=$((pass+1)); printf '  ok   %-58s %s\n' "$1" "$3"
  else fail=$((fail+1)); printf '  FAIL %-58s got %s want %s\n' "$1" "$3" "$2"; fi
}

echo "=== HOLE 1: untracked files invisible to the gate ==="
setup
echo "x = 1" > phsar/app/new_module.py                       # untracked, never shipped
check "new untracked .py via 'git add -A && git commit'" DENY "$(run 'git add -A && git commit -m x')"

echo "=== HOLE 2: git commit -a with a non-empty index ==="
setup
echo "x = 1" > phsar/app/a.py; git add -A >/dev/null; git commit -qm base
echo "doc" > d.md; git add d.md >/dev/null                   # index non-empty
.claude/hooks/mark-reviewed.sh >/dev/null 2>&1
echo "y = 2" >> phsar/app/a.py                     # unstaged, post-ship
check "unstaged .py edit riding along on 'git commit -a'" DENY "$(run 'git commit -a -m x')"

echo "=== HOLE 3: deletion-only change sets ==="
setup
echo "x = 1" > phsar/app/doomed.py; git add -A >/dev/null; git commit -qm base
git rm -q phsar/app/doomed.py
check "pure deletion of a .py, no marker at all"          DENY "$(run 'git commit -m x')"

echo "=== HOLE 4: gate hashed the worktree, commit uses the index ==="
setup
echo "x = 1" > phsar/app/a.py; git add -A >/dev/null; git commit -qm base
echo "x = 1" > phsar/app/a.py
.claude/hooks/mark-reviewed.sh >/dev/null 2>&1              # ship GOOD (no-op tree)
echo "x = 2" > phsar/app/a.py; git add phsar/app/a.py        # stage unreviewed BAD
echo "x = 1" > phsar/app/a.py                                # worktree back to GOOD
check "staged BAD while worktree shows reviewed GOOD"     DENY "$(run 'git commit -m x')"

echo "=== HOLE 5: bare hashes let a new path reuse old content ==="
setup
echo "x = 1" > phsar/app/a.py
.claude/hooks/mark-reviewed.sh >/dev/null 2>&1              # marker now holds a.py's hash
cp phsar/app/a.py phsar/app/copy.py                         # same content, unreviewed path
git add -A >/dev/null
check "new path carrying an already-reviewed blob"        DENY "$(run 'git commit -m x')"

echo "=== POSITIVE CONTROLS (must still ALLOW) ==="
setup
echo "x = 1" > phsar/app/a.py; git add -A >/dev/null
.claude/hooks/mark-reviewed.sh >/dev/null 2>&1
check "properly shipped staged .py"                       ALLOW "$(run 'git commit -m x')"
setup
echo "tiny doc" > small.md; git add -A >/dev/null
check "small doc-only commit, no marker (exempt)"         ALLOW "$(run 'git commit -m x')"
setup
check "non-commit command mentioning the word commit"     ALLOW "$(run 'git log --grep commit')"
setup
check "unrelated command with pr+create in it"            ALLOW "$(run 'gh release create v1 --notes x')"
setup
echo "x" > phsar/app/a.py; git add -A >/dev/null
check "GATE_BYPASS escape hatch"                          ALLOW "$(run 'GATE_BYPASS=1 git commit -m x')"

echo "=== COMMIT FORMS THAT TAKE THE WORKTREE, NOT THE INDEX ==="
# Each of these commits content the index does not hold, so a gate that reads
# only the index waves them through. They are why the gate verifies the union.
setup
echo "x = 1" > phsar/app/a.py; git add -A >/dev/null; git commit -qm base
echo "EVIL = 666" >> phsar/app/a.py                          # unstaged, unshipped
check "pathspec commit: 'git commit -m x <path>'"         DENY "$(run 'git commit -m x phsar/app/a.py')"
setup
echo "x = 1" > phsar/app/a.py; git add -A >/dev/null; git commit -qm base
echo "EVIL = 666" >> phsar/app/a.py
check "'git commit -i <path>' (also -o/--only)"           DENY "$(run 'git commit -i phsar/app/a.py -m x')"
setup
echo "x = 1" > phsar/app/a.py; git add -A >/dev/null; git commit -qm base
echo "EVIL = 666" >> phsar/app/a.py
check "glued quoted -am: 'git commit -am\"msg\"'"           DENY "$(run 'git commit -am"msg"')"
setup
echo "x = 1" > phsar/app/a.py; git add -A >/dev/null; git commit -qm base
echo "EVIL = 666" >> phsar/app/a.py
check "'git commit -aqm\"x\"'"                              DENY "$(run 'git commit -aqm"x"')"
setup
echo "x = 1" > phsar/app/new.py                              # untracked
check "'git stage -A && git commit' (add synonym)"        DENY "$(run 'git stage -A && git commit -m x')"

echo "=== HOLE 4 ON THE OTHER BRANCH: stage-bad, restore-good, with a git add ==="
setup
echo "x = 1" > phsar/app/a.py; echo "y = 1" > phsar/app/b.py
git add -A >/dev/null; git commit -qm base
echo "GOOD = 2" > phsar/app/a.py; echo "y = 2" > phsar/app/b.py
.claude/hooks/mark-reviewed.sh >/dev/null 2>&1               # ship both edits
echo "EVIL = 999" > phsar/app/a.py; git add phsar/app/a.py   # stage BAD
echo "GOOD = 2" > phsar/app/a.py                             # worktree back to reviewed
check "narrow 'git add' cannot hide staged-but-unreviewed" DENY "$(run 'git add phsar/app/b.py && git commit -m x')"

echo "=== DOC-ONLY EXEMPTION ==="
setup
python3 -c "print('word '*4000)" > BIG.md                    # untracked, ~20k bytes
check "large NEW untracked .md via add && commit"         DENY  "$(run 'git add -A && git commit -m x')"
setup
printf 'tiny\n' > small.md
check "genuinely small new doc stays exempt"              ALLOW "$(run 'git add -A && git commit -m x')"

echo "=== TYPE CHANGES (T) ARE NEITHER MODIFY NOR DELETE ==="
setup
echo "x = 1" > phsar/app/a.py; git add -A >/dev/null; git commit -qm base
rm phsar/app/a.py; ln -s /etc/passwd phsar/app/a.py
check "file replaced by a symlink"                        DENY "$(run 'git add -A && git commit -m x')"

echo "=== DELETION-ONLY MUST BE SHIPPABLE (fail-closed regression) ==="
setup
echo "x = 1" > phsar/app/doomed.py; git add -A >/dev/null; git commit -qm base
git rm -q phsar/app/doomed.py
.claude/hooks/mark-reviewed.sh >/dev/null 2>&1
check "deletion-only, after /ship, can actually commit"   ALLOW "$(run 'git commit -m x')"

echo "=== NON-ASCII PATHS MUST NOT DENY FOREVER (fail-closed regression) ==="
setup
echo "x = 1" > "phsar/app/ümlaut.py"
.claude/hooks/mark-reviewed.sh >/dev/null 2>&1
git add -A >/dev/null
check "non-ASCII path after /ship"                        ALLOW "$(run 'git commit -m x')"

echo "=== UNHASHABLE PATHS MUST DENY, NOT ZERO THE CHECK ==="
# hash_paths is all-or-nothing, so one bad path empties the whole worktree half.
# That is indistinguishable from "no files to check" unless it denies explicitly.
setup
echo "x = 1" > phsar/app/a.py; git add -A >/dev/null; git commit -qm base
echo "EVIL = 666" >> phsar/app/a.py                          # unreviewed edit
ln -s /nonexistent/target dangling.link                      # poisons hash_paths
check "dangling symlink cannot hide an unreviewed edit"   DENY "$(run 'git commit -a -m x')"
setup
echo "x = 1" > phsar/app/a.py; git add -A >/dev/null; git commit -qm base
echo "EVIL = 666" >> phsar/app/a.py
mkdir -p vendor && (cd vendor && git init -q .)              # nested repo -> gitlink
check "nested git repo cannot hide an unreviewed edit"    DENY "$(run 'git commit -a -m x')"
setup
echo "x = 1" > phsar/app/a.py; git add -A >/dev/null
printf 'garbage' > .git/index                                # corrupt index
check "corrupt index denies rather than reading as empty" DENY "$(run 'git commit -m x')"

echo "=== STAMPERS MUST NOT DESTROY A GOOD MARKER ==="
setup
echo "x = 1" > phsar/app/a.py; git add -A >/dev/null
.claude/hooks/mark-reviewed.sh >/dev/null 2>&1
before=$(cat .claude/.state/reviewed-ok)
git commit -qm base                                          # tree now clean
.claude/hooks/mark-reviewed.sh >/dev/null 2>&1 || true       # must fail, not wipe
after=$(cat .claude/.state/reviewed-ok 2>/dev/null || echo MISSING)
check "clean-tree /ship leaves the previous marker intact" "$before" "$after"
setup
rm -rf .git; git init -q .; git config user.email t@t; git config user.name t
.claude/hooks/mark-pr-ready.sh >/dev/null 2>&1 || true       # unborn HEAD
check "mark-pr-ready writes nothing on an unborn HEAD" "absent" \
      "$([[ -e .claude/.state/pr-ok ]] && echo present || echo absent)"

echo "=== PR gate ==="
setup
check "gh pr create with no /pr marker"                   DENY-PR "$(run 'gh pr create --fill')"
setup
.claude/hooks/mark-pr-ready.sh >/dev/null 2>&1
check "gh pr create at the stamped tip"                   ALLOW   "$(run 'gh pr create --fill')"
setup
.claude/hooks/mark-pr-ready.sh >/dev/null 2>&1
echo "later" > later.txt; git add -A >/dev/null; git commit -qm later
check "gh pr create after a commit landed post-/pr"       DENY-PR "$(run 'gh pr create --fill')"

echo "=== MISSING TOOLING BLOCKS ONLY WHAT IT CANNOT VERIFY ==="
# The hook matches every Bash call and exit 2 blocks the call it fires on, so
# without the payload pre-filter a missing jq makes the whole repo unusable through
# Claude Code — and reports it as an unverified *commit*, which points nowhere near
# the cause. PATH here holds `bash` (the shebang resolves it) and `cat` (the payload
# read) and nothing else: enough to reach the pre-filter, short of everything the
# gated path needs.
setup
mkdir -p "$WORK/onlycat"
for t in bash cat; do ln -sf "$(command -v "$t")" "$WORK/onlycat/$t"; done
nojq() {  # nojq <command-string> -> the hook's exit code
  # The git-config isolation exported above must survive `env -i`, or a later
  # widening of `onlycat` to include git silently reinstates the developer's
  # commit.gpgsign for these cases alone.
  payload_for "$1" |
    env -i PATH="$WORK/onlycat" HOME="$HOME" \
      GIT_CONFIG_GLOBAL=/dev/null GIT_CONFIG_SYSTEM=/dev/null \
      ./.claude/hooks/review-gate.sh >/dev/null 2>&1
  echo $?
}
check "ungated command survives a toolless PATH"          0 "$(nojq 'ls -la')"
check "gated commit on a toolless PATH still blocks"      2 "$(nojq 'git commit -m x')"
check "gated pr create on a toolless PATH still blocks"   2 "$(nojq 'gh pr create --fill')"

echo "=== UNINSTALLED FRONTEND DEPS ARE AN ENV PROBLEM, NOT A LINT FAILURE ==="
# Only discriminating where bun is installed: without bun the hook warns and allows
# on the first arm instead, so this passes either way rather than reporting a false
# red on a machine that simply has no frontend toolchain.
setup
echo "export const x = 1;" > phsar/frontend/src/a.ts          # no node_modules anywhere
.claude/hooks/mark-reviewed.sh >/dev/null 2>&1
git add -A >/dev/null
check "shipped .ts with no node_modules warns, not denies" ALLOW "$(run 'git commit -m x')"

echo "=== REGRESSION: previously-fixed holes stay fixed ==="
setup
echo "x = 1" > phsar/app/a.py
check "'git add -A && git commit' resolves to commit"     DENY "$(run 'git add -A && git commit -m x')"

echo
echo "passed=$pass failed=$fail"
[[ "$fail" -eq 0 ]]
