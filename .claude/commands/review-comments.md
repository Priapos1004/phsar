Fetch, classify, and resolve PR review comments **and code-scanning (CodeQL) alerts**.

## Arguments

- `$ARGUMENTS`: Optional PR number (e.g., `47`). If omitted, finds the PR for the current branch.

## Steps

1. **Find the PR**: If `$ARGUMENTS` is provided, use it as the PR number. Otherwise, detect the current branch and find its open PR:
   ```bash
   gh pr list --head $(git branch --show-current) --state open --json number --jq '.[0].number'
   ```
   If no PR found, tell the user and stop.

2. **Fetch all comments, replies, AND code-scanning alerts**:
   ```bash
   # Inline review comments (includes replies via in_reply_to_id)
   gh api repos/{owner}/{repo}/pulls/{number}/comments --paginate

   # General PR comments
   gh api repos/{owner}/{repo}/issues/{number}/comments --paginate

   # Review summaries (approve/request-changes body text)
   gh api repos/{owner}/{repo}/pulls/{number}/reviews --paginate

   # Code-scanning (CodeQL etc.) alerts open on THIS PR's head commit
   gh api "repos/{owner}/{repo}/code-scanning/alerts?ref=refs/pull/{number}/head&state=open&per_page=100" \
     --jq '.[] | {number, rule: .rule.id, severity: .rule.severity, path: .most_recent_instance.location.path, line: .most_recent_instance.location.start_line, commit: .most_recent_instance.commit_sha[0:8], msg: .most_recent_instance.message.text}'
   ```
   Group reply comments under their parent (match via `in_reply_to_id`). Display replies indented under the parent in the detail section.

   **Confirm the scan is current before trusting it.** Code scanning runs asynchronously after a push, so a "failing github-advanced-security check" may just be a stale result from an earlier commit. Check which commit was last analyzed and compare to the PR head:
   ```bash
   gh api "repos/{owner}/{repo}/code-scanning/analyses?per_page=8" \
     --jq '.[] | {commit: .commit_sha[0:8], ref, created: .created_at, results: .results_count, category}'
   gh rev-parse HEAD   # or: gh pr view {number} --json headRefOid -q .headRefOid
   ```
   If the latest analysis commit ≠ PR head, say so — the alerts shown may not reflect the newest push; offer to re-check after the scan completes rather than acting on stale data.

3. **Classify each top-level comment AND each alert** into exactly one category:
   | Classification | Icon | Description |
   |---|---|---|
   | **bug** | :beetle: | Points out incorrect behavior, logic errors, crashes |
   | **security** | :lock: | Code-scanning/CodeQL alert, or a human comment flagging a vulnerability (injection, auth, secrets, path traversal) |
   | **improvement** | :wrench: | Suggests better approach, refactor, performance, or maintainability |
   | **question** | :question: | Asks for clarification or rationale |
   | **nitpick** | :pushpin: | Style, naming, formatting, minor preference |
   | **praise** | :star: | Positive feedback, approval |

4. **Display as a markdown table**, grouped by classification priority (bugs first, then security, … praise last). Within each group, order by file path then line number.

   Format:
   ```
   ## PR #{number} Review Comments & Scan Alerts

   Found {N} comment threads from {authors} and {M} open code-scanning alerts.

   | # | Class | File | Line | Comment / Rule | Replies | Source |
   |---|-------|------|------|----------------|---------|--------|
   | 1 | :beetle: bug | `dao.py` | 42 | Description search should use LEFT JOIN to... | 2 | @reviewer |
   | 2 | :lock: security | `backup_service.py` | 290 | py/path-injection (error): user value reaches... | — | CodeQL #7 |
   | 3 | :wrench: improvement | `service.py` | 88 | Consider batching these DB calls with asyncio... | 0 | @reviewer |
   ```

   - Truncate text to ~80 chars, append "..." if truncated
   - For general (non-inline) comments, leave File and Line columns as `--`
   - For code-scanning alerts, the Source column is `CodeQL #{alert_number}` and "Comment / Rule" is `{rule_id} ({severity}): {message}`
   - Show reply count per comment thread (`—` for alerts)
   - Show the full text + all replies below the table for any bug- or security-classified items

5. **Verify each item against the actual code** before presenting. Do not blindly trust reviewers or the scanner.
   - For comments: read the referenced code; decide valid / invalid / already-fixed, with a brief reason.
   - For code-scanning alerts: read the flagged sink **and trace the source-to-sink path**. Decide whether it's a **true finding** (needs a code fix) or a **false positive** (the input is already constrained by a guard the query doesn't model — e.g. a regex/allowlist sanitizer CodeQL doesn't recognize). Note the verdict + reasoning. If a sibling alert on the same mechanism was already dismissed on `main` or an earlier commit, say so — it's precedent.

   Present invalid / false-positive items separately so the user sees what was filtered out and why.

6. **Ask the user** which items to address. Do not start fixing or dismissing anything automatically. For code-scanning alerts, frame the choice explicitly: **fix the code** (preferred when the finding is real or a code change can satisfy the query) vs **dismiss as false positive** (legitimate when the guard is real but the query won't credit it).

   ⚠️ **A code fix doesn't always satisfy the scanner.** Some queries (notably `py/path-injection`) don't recognize common sanitizers — a regex allowlist, `Path.resolve()` + `is_relative_to()`, etc. Adding such a guard can leave the alert open *and* introduce new alerts on the guard's own lines. If you propose a code fix to clear a scan alert, say it's not guaranteed to work and that dismissal may still be needed. Don't add hardening whose only purpose was to satisfy CodeQL if it fails to.

7. **Resolve each addressed item.**

   **Review comments** — after fixing, reply explaining what was done:
   ```bash
   gh api repos/{owner}/{repo}/pulls/{number}/comments/{comment_id}/replies -f body="Fixed: <what changed> (<commit sha>)"
   # general issue comments:
   gh api repos/{owner}/{repo}/issues/{number}/comments -f body="Addressed: <what changed>"
   ```

   **Code-scanning alerts:**
   - *If fixing in code*: push the fix, then let the next scan resolve the alert automatically (it flips to `fixed`). Verify with the step-2 alerts query against the new head.
   - *If dismissing as a false positive*:
     ```bash
     gh api -X PATCH repos/{owner}/{repo}/code-scanning/alerts/{alert_number} \
       -f state=dismissed \
       -f dismissed_reason="false positive" \
       -f dismissed_comment="<short justification>"
     ```
     - `dismissed_reason` MUST be one of: `false positive`, `won't fix`, `used in tests`.
     - `dismissed_comment` is capped at **280 characters** — keep it short (the API 422s otherwise).
     - The `github-advanced-security` check gates on *open* alerts introduced by the PR; once every alert is `fixed` or `dismissed`, it goes green on its next evaluation (may lag the dismissal by a scan cycle).
   - If a reverted code-fix attempt left alerts on now-deleted lines, dismiss those too (or let the next scan mark them `fixed`) so there's no open-alert window.

   When the resolution diverges from an earlier reply/comment (e.g. a hardening attempt was reverted), post a short correction comment on the PR so the record stays accurate.
