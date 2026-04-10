# Phsar Roadmap — Feature Design & Planning

This document captures design decisions from the feature brainstorming session.
Once all features are discussed, this becomes the basis for GitHub issues and milestones.

---

## Feature 1: Ratings System

### DB Design

**Rating table** (per user, per media — extends existing model):

| Field | Type | Required | Notes |
|---|---|---|---|
| `rating` | Float 0-10 | yes | Two decimal precision in DB, UI step controlled by user settings |
| `dropped` | Boolean | yes | default False, explicit intent flag |
| `episodes_watched` | Integer | no | Auto-filled on "completed" if total known; nullable for unknown ep counts; backfilled by data update pipeline |
| `note` | String | no | Anime-wide notes go on one media (first/last selected) |
| `pace` | Enum | no | slow / normal / fast |
| `animation_quality` | Enum | no | bad / normal / good / outstanding |
| `has_3d_animation` | Enum | no | none / partial / full |
| `watched_format` | Enum | no | sub / dub / both |
| `fan_service` | Enum | no | none / rare / normal / heavy |
| `dialogue_quality` | Enum | no | flat / normal / deep |
| `character_depth` | Enum | no | flat / normal / complex |
| `ending` | Enum | no | open_cliffhanger / not_satisfying / satisfying / great |
| `story_quality` | Enum | no | weak / average / good / outstanding |
| `originality` | Enum | no | conventional / unique / experimental |

**RatingSearch table** (new, mirrors MediaSearch pattern):
- `rating_id` (FK)
- `note_embedding` (Vector 384-dim) — generated when note is saved/updated

### Key Decisions
- Ratings always live at media level — no anime-level rating table
- "Rate whole anime" = UI/service convenience: select multiple media, write one Rating row per media with same score
- Note attached to first/last selected media when bulk-rating
- `dropped` kept as explicit boolean (not derived from episodes_watched vs total) because media.episodes can be NULL, can change, and intent matters
- `episodes_watched` nullable — data update pipeline backfills when episode counts become available
- All attributes are scales (not positive-only flags) for richer filtering and analysis
- Attributes are personal per-user opinions, but designed so cross-user aggregation works later
- Users only see their own ratings
- Rating something on watchlist → pop-up asks if it should be removed
- Ratings and watchlist are independent (all four combinations valid)

### Future Features
- "Give it a second chance" browsing section (dropped anime) — computed from ratings data
- "I break up before it breaks me" section (dropped bad anime) — computed from ratings data
- "Love it or hate it" recommendations — derived from MAL vote distributions + user ratings

### Achievements System (v0.18.0+)

**Achievement table** (definitions):

| Field | Type | Notes |
|---|---|---|
| `id` | PK | |
| `name` | String | internal identifier |
| `title` | String | funny display title for user profile (e.g. "Truck-kun Tamer", "Isekai Veteran") |
| `description` | String | how to unlock |
| `rarity` | Enum | e.g. common / uncommon / rare / epic / legendary |

**UserAchievement table** (junction):

| Field | Type | Notes |
|---|---|---|
| `user_id` | FK → users.id | |
| `achievement_id` | FK → achievement.id | |
| `unlocked_at` | DateTime | when achieved |

**Behavior:**
- After each rating, a service checks if new achievements are triggered
- Milestones: 1, 5, 10, 50, 100, 150, 200... anime watched / time watched / all MAL genres covered
- Genre titles: funny titles based on most-watched genre
- User profile shows rarest 1-3 titles from their unlocked achievements
- Achievement overview page on user profile (all achievements, locked and unlocked)
- Private — not visible to other users

---

## Feature 2: Anime-Level Aggregation & Pages

### Anime-Level Search (new default)

**New endpoint:** `GET /search/anime` — groups media by parent anime, returns aggregated results.

**Aggregation rules:**

| Field | Aggregation |
|---|---|
| Score | Average MAL score across all media |
| Total watch time | Sum across all media |
| Episodes | Sum across all media |
| Vector search (description) | Average cosine distance across all media of an anime — consistently relevant anime ranks higher than single lucky match |
| Vector search (title) | Match against anime's own title/names directly |

**Filter behavior at anime level:**

| Filter | Logic |
|---|---|
| Genre | Strict majority (>50% of media must have genre). 1/1=yes, 1/2=no, 2/3=yes, 2/4=no |
| Studio | Any (if any media has the studio, anime matches) |
| Season | Any (match if any media aired in that season) |
| Airing status | Can have multiple statuses simultaneously. "Currently Airing" if any media is currently airing. "Not yet aired" if any media is not yet aired. "Finished Airing" only if all media are finished. An anime can be both "Currently Airing" AND "Not yet aired" (e.g., season 3 airing now + season 4 announced). Filtering: anime matches if it has ANY of the selected statuses. |
| Media type, relation type | Any |
| Age rating | Max across all media (e.g., if one OVA is R+ but rest is PG-13, anime shows R+ so PG-13 filter excludes it) |
| Range filters (score, episodes, watch time, etc.) | Applied against aggregated values (avg score, sum episodes, sum watch time) |

**Search toggle UX:**
- Default view: anime-level search
- Separate toggle (not in filter panel — it's a view change, not a filter)
- Toggle switches between anime and media result views

### Anime Detail Page (`/anime?uuid=...`)

- Anime metadata: title, names, cover image (from anime table), description, age rating, genres, studios, seasons, airing status, total episodes, total watch time, avg score
- List of all media (clickable → media detail page)
- User's ratings summary for this anime (if any exist)
- "Rate all" action: select multiple media, apply same score in bulk
- Watchlist actions: add all media to watchlist / remove all from watchlist / select specific media to add

### Media Detail Page (`/media?uuid=...`)

- Full media info (expanded version of MediaInfo card)
- Rating UI: popup/modal for creating/editing a rating
- Link back to parent anime page
- User's existing rating displayed (if exists)
- Watchlist action: add/remove this media from watchlist

### Key Decisions
- Vector search results don't surface which media matched — feels like browsing anime, not media
- Anime cover shown on anime page is from the anime table (not media covers)
- Media-level search stays available via toggle for power users

---

## Feature 3: User Settings & Profile

### DB Design

**UserSettings table** (one-to-one with User, separate from User to keep static/dynamic apart):

| Field | Type | Default | Notes |
|---|---|---|---|
| `user_id` | FK → users.id | required | unique, one-to-one |
| `profile_picture` | Enum/String | first option | Fixed set of 10-20 bunny-anime-character images |
| `name_language` | Enum | english | english / japanese / romaji |
| `default_search_view` | Enum | anime | anime / media |
| `rating_step` | Enum | 0.5 | 0.5 / 0.25 / 0.1 / 0.01 |
| `spoiler_protection` | Boolean | false | Hides descriptions and covers of unrated media. Default set during get-started onboarding. |

### Profile Pictures
- Fixed set of 10-20 images shipped with the app (no user uploads)
- Each has a distinct color/theme
- Future: website theme (CSS custom properties) changes based on selected profile picture

### Spoiler Protection Behavior
- When enabled:
  - Hide descriptions until clicked/tapped
  - Hide cover images of media the user hasn't rated yet
  - Optionally: only show first-season anime or "continue watching" entries in search results
- Applies in search results, anime pages, media pages

### Key Decisions
- No profile visibility setting — users are always separated
- Cross-user data only used in background for recommendations and aggregate browsing ("others rated 8.5+")
- No NSFW filter for now (can be added later as a setting)
- No notification setting yet (deferred until content pipeline feature)
- Theme color derived from profile picture, not a separate setting
- Settings created with defaults when user account is created

### Implementation Note (from v0.10.0)
- When `rating_step` changes, existing ratings may have precision that doesn't match the new step (e.g. a score of 7.25 saved with step 0.25, then user switches to step 0.5). Decide on display behavior: show the stored value as-is (preserving precision), or round to the current step for display consistency. The score input already uses `clampAndSnapScore(val, step)` which will snap on edit, but read-only display needs a policy.

---

## Feature 4: Content Pipeline (Add Anime, Updates, Seasonal Scraping)

### User-Triggered "Add Anime"

**Who**: Any user except `restricted_user`.

**Flow:**
1. User searches MAL via existing `/search/mal` → selects anime to add
2. Server creates a job entry in DB, starts background processing
3. Scraper BFS traverses MAL relations, fetching media details and generating embeddings
4. User polls for progress via `GET /jobs/{id}` or sees status in navbar bell/notification area

**Rate limiting:**
- Max 4 concurrent scrape jobs per user
- Job table tracks status: `queued → running → completed → failed`
- Race guard: `SELECT ... FOR UPDATE` on user's running jobs before allowing new one
- If user has 4 running jobs, new request is rejected until one completes

**Progress tracking (stage-based, honest about growing totals):**
- "Discovering related media... (found 12 so far)"
- "Fetching details: 3/12 discovered..."
- "Fetching details: 12/23 discovered..." (denominator grows as BFS finds more)
- "Generating embeddings: 5/23"
- "Done — added [Anime X] with 23 media entries"

**Job table:**

| Field | Type | Notes |
|---|---|---|
| `id` | PK | |
| `user_id` | FK → users.id | who triggered it |
| `status` | Enum | queued / running / completed / failed |
| `stage` | String | current stage description |
| `media_discovered` | Integer | total found so far (grows during BFS) |
| `media_processed` | Integer | fetched/embedded so far |
| `anime_title` | String | for display |
| `result_summary` | String | nullable, filled on completion |
| `error_message` | String | nullable, filled on failure |
| `created_at` | DateTime | |
| `completed_at` | DateTime | nullable |

### Deduplication

**Multi-layer approach:**
1. **MAL ID match**: Before inserting any media, check if `mal_id` already exists → attach to existing anime
2. **Title + metadata similarity**: If a newly scraped media's anime title closely matches an existing anime (same name + similar description or same studio), flag for admin review — do NOT auto-merge
3. **Admin notification**: Potential duplicates trigger Discord webhook + in-app notification for admin. No automatic merge — could indicate MAL re-indexing which would be a major problem if handled wrong.

**BFS boundary rule (change from current behavior):**
- Current scraper: two-phase BFS — freely explores to find "main story", then only follows relations from main story media. Already skips `character` and `adaptation` relations. Crossovers ARE currently followed and included in same anime group.
- Proposed change: Stop following `crossover` relations during BFS — crossover media gets its own parent anime. Store crossover media with `relation_type="crossover"` but don't merge into same anime group.
- This naturally separates franchises like FATE into distinct anime entries
- Side stories are already limited (only explored from main story branches, not recursively)

**Merge handling:**
- If BFS from a new scrape overlaps with media already in DB (different parent anime), this flags a potential merge situation
- Admin-only merge capability — never automatic

### Automated Updates (Periodic)

**Triggered via**: Coolify scheduled task (cron) calling an internal endpoint.

**What it does for each existing anime:**
- Re-queries MAL for each media: update airing status, episode counts, scores, scored_by, aired_to dates
- Check for new media releases by re-traversing relations (new season announced?)
- Backfill `episodes_watched` on user ratings where episodes count was previously NULL and is now known
- Re-traverses relation graph to detect if separate anime entries should be flagged for merge

**Frequency**: Daily or weekly (TBD based on MAL API rate limits and DB size). Existing anime updates may be weekly; seasonal updates can be daily (only 20-30 anime per season, most MAL IDs already in DB after first fetch).

### Seasonal Scraping

**Triggered via**: Coolify scheduled task (weekly).

**What it does:**
- Scrapes all anime from the current MAL season
- Adds new anime not already in DB
- Deduplication rules apply (MAL ID check, title similarity flagging)
- Starts from the season the feature launches, going forward only

---

## Feature 5: Watchlist

### DB Design (already exists, no changes needed)

**Watchlist table** (per user, per media):

| Field | Type | Notes |
|---|---|---|
| `user_id` | FK → users.id | |
| `media_id` | FK → media.id | |
| `note` | String | optional |
| `priority` | Integer 1-3 | 1=low, 3=high |

**Tag table** (per user):

| Field | Type | Notes |
|---|---|---|
| `user_id` | FK → users.id | |
| `name` | String | free-text, e.g. "Overpowered MC", "recommendation from Lewis", "Good for lunch" |
| `color` | String | hex color |

**WatchlistTag** junction table links tags to watchlist entries.

### Key Design
- Tags and priority are **independent dimensions** — can be combined freely but not nested
- Storage at media level, UI groups by parent anime
- Watchlist icons visible in search results (already added indicator + quick-add button)
- Rating an anime on watchlist → popup asks if it should be removed

### Watchlist Page UI
- Standard view: covers + titles with filtering by tags, priority
- Link to browse page for deeper exploration

---

## Feature 5b: Browse Page

### Concept
Separate page/route — the "deep dive" version of home page sections.

**Toggle**: "All anime in DB" vs "Only my watchlist"

### Sections (horizontal scrollable card rows — Crunchyroll-style, same as home page)
- **Recommendation algo** (top of page) — dropdown/selector to choose algorithm. Designed for experimentation — swap in new algos over time, users can try different ones. Could also be a user setting.
- **Give it a second chance** — dropped anime (from ratings data)
- **Continue watching** — anime on watchlist with partial ratings (e.g. watched S1, S2 waiting)
- **Genre-based sections** — "Vampire Lovers", "Isekai Adventures", etc. (derived from user's top-rated genres)
- **Unexplored territory** — cluster-based discovery, anime outside user's usual selection
- **Others also liked** — cross-user signal (users who rated similar anime highly)
- **Rising on MAL** — high `log(scored_by) * score` weighting

### Recommendation Algorithms (iterative, start simple)

**v1 (simple):**
- Weighted MAL score: `log(scored_by) * score`
- Top watchlist picks: prio 3, mix of old and new additions
- "Others also liked" based on overlapping high ratings

**v2+ (advanced, future):**
- User rating + actuality combo
- Pattern prediction (isekai → romance cooldown cycle detection)
- HDBSCAN clustering over description embeddings — find gaps in user's coverage
- Production company analysis over embeddings

### Key Decisions
- Algorithm selector (dropdown or user setting) keeps backend flexible for experimentation
- Advanced recommendation algos are separate work items — not blocking browse page v1
- Browse page and home page share section components but home is lightweight subset

---

## Feature 5c: Home Page

### Concept
Eye-catching landing page — light version of browse, serves new and returning users.

### Sections (keep existing placeholders, horizontal scrollable card rows — Crunchyroll-style)
- **Current season diashow** (existing) — rotate through new anime of the season
- **Recommended** (existing placeholder) — from selected algo
- **Lucky Find** (existing placeholder) — surprise/random picks
- **Upcoming** (existing placeholder) — upcoming anime releases

### UI Pattern
- Horizontal scrollable card rows (like Crunchyroll app) for all sections
- Same pattern used on browse page — lots of options in compact space
- Anime cover cards that scroll left/right

### Key Decisions
- Recommendation section uses same algo as browse page top section
- Home page sections reuse browse page components (lighter presentation)
- For logged-out / new users: show season diashow, popular, recently added (skip personalized sections)
- `RelatedMediaCarousel` (from v0.10.0) is a starting point — generalize it into a reusable horizontal card carousel component that accepts any card content (anime covers, media cards, recommendations) for both browse and home page sections

---

## Feature 6: Search & Browse Enhancements

### Approach: One Search Bar, Contextual Filters
- Reuse the same SearchBar component everywhere, with context-dependent filter options
- On `/search`: full filters + two new toggles: "in watchlist" / "already watched"
- On watchlist page: same search bar, pre-filtered to watchlist items, plus tag/priority filters
- On browse page: same search bar, collapsed by default (sections are main navigation)
- Avoids building multiple search components

### New Filters
- **In watchlist** (boolean toggle) — filter results to only anime on user's watchlist
- **Already watched** (boolean toggle) — filter to anime the user has rated
- These require joining against user's watchlist/ratings tables in the search query

### General Browsing
- Browse page (Feature 5b) covers this — sections + search bar with filters gives full browsing capability
- No separate "all anime" page needed if browse page has "all anime in DB" toggle

---

## Feature 7: User Data Export

### What
- User downloads their own data as flat media-level rows (one row per media with a rating or watchlist entry)
- No embeddings included
- Purpose: personal analysis of own ratings and watchlist data

### Format
- CSV or JSON (user chooses via query param)
- Endpoint: `GET /users/export?format=json|csv` (authenticated, user/admin only)
- Filename: `phsar_export_{username}_{YYYY_MM_DD}.json/csv`

### Contents per row
- **Anime/media catalog**: anime_title, (anime_name), title, (name), anime_mal_id, mal_id, type, relation, episodes, episode_duration_seconds, season, season_year, age_rating, mal_score, mal_scored_by
- **Rating data** (null if only watchlisted): rating, dropped, episodes_watched, rating_note, rated_at, rating_updated_at, + 11 attribute enums
- **Watchlist data** (null if only rated): watchlist_priority, watchlist_note, watchlist_tags, watchlist_added_at
- **Conditional name columns**: `anime_name` and `name` only included when user's `name_language` setting is not romaji and at least one resolved name differs from the romaji title

### Key Decisions
- Flat media-level structure (not separate ratings/watchlist sections) for analysis-ready data
- Includes MAL scores for correlation analysis, season/age_rating/duration for user analytics
- Name columns are conditional to avoid empty columns when user uses romaji

### Future
- Document the export schema (column definitions, conditional columns, format differences) on the getting-started page

---

## Feature 8: Database Backup & Restore

### Why
- Users will invest significant effort (200+ ratings) — data loss is unacceptable
- Need both automated snapshots and manual restore capability

### Approach: pg_dump + dual storage

**Server-side (automated):**
- Admin endpoint triggers `pg_dump` → compressed backup file
- Stored on server disk (or object storage if available)
- Coolify cron for scheduled backups (daily or weekly)
- Admin can download backup file or trigger restore via admin panel

**Local backup (safety net):**
- Admin can download dump file from admin panel to local machine
- Periodic manual download or scripted pull
- Last resort if server itself has issues

**Restore:**
- Admin endpoint for `pg_restore` from uploaded or server-stored backup
- Requires confirmation step (destructive operation)

---

## Feature 9: Statistics & Analytics

### Scope: High-level for now — endless ideas, will detail iteratively

### Standard Graphs
- Watch history over time
- Genre distribution (what genres user watches most)
- Score distribution (histogram of user's ratings)
- Watch time stats (total, by genre, by year)
- Dropped rate by genre/studio
- Rating attribute distributions (pace, animation quality, etc.)

### Advanced Analytics (later iterations)
- HDBSCAN clustering over description embeddings — 2D map of all anime, highlight unexplored areas
- Production company analysis over embeddings
- Monthly pre-computed reports (if real-time reprocessing is too expensive)
- Pattern detection (genre rotation habits, seasonal preferences)

### Key Decisions
- Start with standard graphs, add advanced analytics incrementally
- May need pre-computed/cached results for expensive operations (clustering, embedding analysis)
- Statistics page is its own route, user-specific data only

---

## Feature 10: Get-Started Page

### Concept
- Mandatory onboarding flow — forced on first login, user must complete it before accessing the app
- Serves as tutorial + initial settings configuration
- User sets: profile picture, name language, rating step, spoiler protection, default search view
- Brief walkthrough of key features (search, ratings, watchlist)

---

## Feature 11: Home Page Design

*Visual design and layout — separate from functional home page sections (Feature 5c)*

---

## Milestone & Issue Organization

### Version Roadmap

| Version | Scope | Notes |
|---|---|---|
| **v0.9.0** | ✓ Ratings backend + rating enums/migration + DAO optimization | Pure backend. Lock DB schema for ratings. Clean up DAO query patterns (single-queries) while touching this layer. |
| **v0.10.0** | ✓ Media detail page + rating UI | First visible ratings. Rating modal/popup. Media page with full info + link to anime (anime page not yet built). |
| **v0.11.0** | ✓ Anime-level search + anime detail page | Aggregated search as default. Anime↔media navigation loop complete. View toggle (anime/media). View-type-aware filter options. |
| **v0.12.0** | User settings + user page UI + data export + admin + account deletion | Settings table, profile pictures, rating step, name language, spoiler protection. Flat media-level data export (ratings + watchlist + catalog info per media, respects name_language, dated filename). Token expiry dialog. Registration page. Guest account. Admin page for registration token management. Account deletion with glass crack UX, password confirmation, DB cascade (SET NULL on registration tokens). |
| **v0.13.0** | Deployment (Coolify) + switch to bun + DB backup/restore | Deployment-ready: Coolify config for db/frontend/backend services. Switch frontend from npm to bun. pg_dump backup system (automated + local download). Prerequisite for content pipeline cron jobs. |
| **v0.14.0** | Content pipeline (scraper jobs, dedup, updates, seasonal) | User-triggered scraping with job tracking. Automated daily/weekly updates. Seasonal scraping. Dedup + admin merge notifications. |
| **v0.15.0** | Watchlist backend + UI | Watchlist CRUD, tags, priority. Watchlist page with filtering. Watchlist icons in search results. |
| **v0.15.1** | Search enhancements + design polish | "In watchlist"/"already watched" search filters. Search filter QoL improvements. Component design polish. Note: consider enlarging the watchlist bookmark icon on the media detail page for better tap target and visual presence. |
| **v0.16.0** | Browse page + home page redesign | Crunchyroll-style horizontal card rows. Browse sections with algo selector. Home page as light version. Get-started page. |
| **v0.17.0** | Statistics & analytics (v1) | Standard graphs (watch history, genre distribution, score histogram, etc.). Statistics page route. |
| **v0.18.0+** | Advanced recommendations, achievements, advanced analytics | HDBSCAN clustering, pattern prediction, "love it or hate it", achievements system with titles. Iterative. |

### Key Dependencies
- v0.10.0 (media pages) depends on v0.9.0 (ratings backend)
- v0.11.0 (anime search) depends on v0.10.0 (media pages exist to link to)
- v0.13.0 (deployment) must come before v0.14.0 (content pipeline needs Coolify cron)
- v0.15.0 (watchlist) depends on v0.11.0 (anime/media pages for navigation)
- v0.16.0 (browse) depends on v0.15.0 (watchlist) + v0.9.0 (ratings) for section data
- v0.17.0 (statistics) depends on v0.9.0 (ratings data to analyze)
