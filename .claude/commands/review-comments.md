Fetch, classify, and resolve PR review comments.

## Arguments

- `$ARGUMENTS`: Optional PR number (e.g., `47`). If omitted, finds the PR for the current branch.

## Steps

1. **Find the PR**: If `$ARGUMENTS` is provided, use it as the PR number. Otherwise, detect the current branch and find its open PR:
   ```bash
   gh pr list --head $(git branch --show-current) --state open --json number --jq '.[0].number'
   ```
   If no PR found, tell the user and stop.

2. **Fetch all comments and replies**: Get review comments (inline on code), their reply threads, and general issue comments:
   ```bash
   # Inline review comments (includes replies via in_reply_to_id)
   gh api repos/{owner}/{repo}/pulls/{number}/comments --paginate
   
   # General PR comments
   gh api repos/{owner}/{repo}/issues/{number}/comments --paginate
   
   # Review summaries (approve/request-changes body text)
   gh api repos/{owner}/{repo}/pulls/{number}/reviews --paginate
   ```
   Group reply comments under their parent (match via `in_reply_to_id`). Display replies indented under the parent in the detail section.

3. **Classify each top-level comment** (not replies) into exactly one of these categories based on its content:
   | Classification | Icon | Description |
   |---|---|---|
   | **bug** | :beetle: | Points out incorrect behavior, logic errors, crashes |
   | **improvement** | :wrench: | Suggests better approach, refactor, performance, or maintainability |
   | **question** | :question: | Asks for clarification or rationale |
   | **nitpick** | :pushpin: | Style, naming, formatting, minor preference |
   | **praise** | :star: | Positive feedback, approval |

4. **Display as a markdown table**, grouped by classification priority (bugs first, praise last). Within each group, order by file path then line number.

   Format:
   ```
   ## PR #{number} Review Comments

   Found {N} comment threads from {authors}.

   | # | Class | File | Line | Comment | Replies | Author |
   |---|-------|------|------|---------|---------|--------|
   | 1 | :beetle: bug | `dao.py` | 42 | Description search should use LEFT JOIN to... | 2 | @reviewer |
   | 2 | :wrench: improvement | `service.py` | 88 | Consider batching these DB calls with asyncio... | 0 | @reviewer |
   ```

   - Truncate comment text to ~80 chars, append "..." if truncated
   - For general (non-inline) comments, leave File and Line columns as `--`
   - Show reply count per thread
   - Show the full comment text + all replies below the table for any bug-classified items

5. **Verify each comment against the actual code** before presenting. Do not blindly trust review comments — read the referenced code and check whether the comment is actually valid, still relevant (may have been fixed in a later commit), or based on a misunderstanding. For each comment, note its validity status (valid, invalid, already fixed, etc.) with a brief reasoning. Present invalid/not-applicable comments separately so the user can see what was filtered out and why.

6. **Ask the user** which comments they want to address. Do not start fixing anything automatically.

7. **After fixing each comment**, resolve it by posting a reply comment on the PR explaining what was done:
   ```bash
   gh api repos/{owner}/{repo}/pulls/{number}/comments/{comment_id}/replies -f body="Fixed: <brief description of what was changed>"
   ```
   For general issue comments, reply on the issue:
   ```bash
   gh api repos/{owner}/{repo}/issues/{number}/comments -f body="Addressed: <brief description>"
   ```
