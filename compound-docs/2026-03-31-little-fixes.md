---
branch: little-fixes
date: 2026-03-31
scope: backend, frontend, security, data model
---

## Summary

Batch of cross-cutting improvements: Argon2 password migration with transparent rehashing, `fsk`-to-`age_rating` rename, anime season column decomposition, genre descriptions, hentai content filtering, and several frontend search UX fixes (log-scale slider, description vector search toggle, clear-all button).

## Key Decisions

- **Argon2 over bcrypt**: Switched password hashing to Argon2id with a rehash-on-login strategy. Used a `DUMMY_HASH` constant for timing-safe comparison when user doesn't exist, and a race-guarded conditional UPDATE to avoid clobbering concurrent rehashes.
- **Season split into two columns**: Decomposed the free-text `anime_season` string into `anime_season_name` (enum) + `anime_season_year` (int) with a both-or-none CHECK constraint. This enables typed filtering via `tuple_().in_()` instead of string matching.
- **Genre descriptions nullable**: Made `description` a nullable `Text` column since nothing reads it yet — purely a data-layer addition for future hover tooltips.

## Gotchas

- `add_columns()` on an ORM query changes return shape to tuples, but `.scalars().all()` silently extracts only the first column. Hybrid properties masked the issue since they recompute in Python. Removed the dead `add_columns` during PR review.
- JavaScript `null + " " + null` produces the string `"null null"`, not an empty/null value. Required an explicit null guard for nullable season fields in the frontend template.
- `passlib` is unmaintained and emits deprecation warnings on Python 3.12+. Consider migrating to `argon2-cffi` directly in a future release.

## Future Work

- Hardcoded CORS origin and frontend API URL block non-localhost deployment (address in v0.8.0)
- `fetch_filter_values` issues 12+ sequential DB queries — could use `asyncio.gather`
- N+1 pattern in `create_unwanted_media` (same fix as genre seeder)
- `passlib` replacement with direct `argon2-cffi`
