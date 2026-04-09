Create a new GitHub release for the phsar project.

## Steps

1. **Determine version**: List existing tags sorted by version. Until v1.0.0, use the following versioning scheme based on the nature of the changes:
   - **Minor bump** (e.g. v0.7.0 -> v0.8.0): New features, breaking changes, or significant additions.
   - **Patch bump** (e.g. v0.7.0 -> v0.7.1): Bug fixes, maintenance, small improvements, or cleanup only.
   Propose the version to the user based on the changes — they have the final say. If the user provided arguments, treat them as an explicit version override.
2. **Collect changes**: Get all commits between the latest tag and HEAD using `git log --oneline {latest_tag}..HEAD`.
3. **Draft release notes**: Summarize commits into a human-readable release note following the format below. Group changes logically - not 1:1 with commits. Only include sections that have entries.
4. **Present for confirmation**: Show the user the proposed version, tag, and full release notes. Ask for confirmation before proceeding. Do NOT create anything without explicit approval.
5. **Create tag and release**: Once confirmed, create the git tag on HEAD, push it, and create the GitHub release via `gh release create`.

## Release Notes Format

```
{One-line summary describing the release theme.}

### Features
- ...

### Bug Fixes
- ...

### Maintenance
- ...

### Breaking Changes
- ...

**Full Changelog**: https://github.com/Priapos1004/phsar/compare/{previous_tag}...{new_tag}
```

- The "Breaking Changes" section should only appear if there are actual breaking changes.
- Omit any section that has no entries.
- The one-line summary should capture the overall theme, not list everything.
- Keep bullet points concise and feature/fix-level (not commit-level).
- Only mention things that are meaningful relative to the *previous release*. Bugs introduced and fixed within the same cycle, internal refactors of code that didn't exist in the previous release, and meta changes to tooling/skill files are not user-facing — fold them into the related feature or omit them entirely.

## Arguments

$ARGUMENTS
