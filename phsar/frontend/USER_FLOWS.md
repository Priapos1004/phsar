# User Flows — Test Specification

This document describes the user-facing behavior of the PHSAR frontend. It serves as the source of truth for what should still work after the shadcn/runes migration.

---

## 1. Authentication

### 1.1 Login
- User sees a centered card with username/password fields and a "Login" button
- Page background is a themed light-to-deep gradient matching the active theme (purple / red / blue / green), driven by the theme class pre-applied from localStorage by the FOUC script in `app.html`
- Submitting the form POSTs credentials to `/auth/login` (URL-encoded)
- On success: token is stored in localStorage, user is redirected to `/`
- On invalid credentials: error message appears below the form in red
- On network error: "An unexpected error occurred." message appears
- While submitting: button shows "Logging in..." and is disabled

### 1.2 Auth Guard
- Navigating to any route except `/login` without a token redirects to `/login`
- On every page load, the stored token is validated via `GET /auth/validate`
- If validation returns 401, token is cleared from localStorage and user is redirected to `/login`

### 1.3 Logout
- Clicking "Logout" in the NavBar dropdown clears the token immediately, shows a ~1.5s themed sakura-ring loading screen as a soft transition, then redirects to `/login`
- Involuntary logouts (401 from API, token expiry, account deletion) skip the animation and redirect instantly

### 1.4 Token Persistence
- Token is stored in and loaded from localStorage
- Closing and reopening the browser keeps the user logged in (until token expires or is invalidated)

### 1.5 Maintenance Mode
- **Sticky pre-warning banner.** A yellow `Notice` card sits in a sticky container at the top of every page (including `/login` and `/register`), pinned alongside the navbar so scrolling the page keeps both visible. Renders only when a maintenance window is upcoming or active.
  - Polls `GET /maintenance/status` every 30s via raw `fetch` (deliberately bypasses the API client so a 503 mid-window can't trigger the redirect below and defeat the warning). 30s instead of 60s so the seasonal-sweep dispatcher's short maintenance window (which can be only a few seconds long since the per-id MAL work runs in child jobs) is still observable for idle sessions.
  - Also subscribes to the auth `token` store and to a shared `maintenanceRefresh` bump signal — any login/logout transition AND any 503-with-maintenance response triggers an immediate refetch, so the banner reacts in milliseconds rather than waiting for the next 30s poll.
  - When `scheduled_at` is within 30 min: "Scheduled maintenance starts in ~N minutes — pause your current episode." (singular "minute" at exactly 1).
  - When `active` is true: "Maintenance in progress. Please try again later."
  - When neither: banner is hidden.
- **Mid-window redirect.** When the backend returns 503 with `{maintenance: true}` on *any other* request, the API client clears the token, bumps `maintenanceRefresh` so the global banner refetches state immediately, and hard-navigates to `/login` (when the user wasn't already there).
- **/login during a maintenance window.** The form has no inline maintenance message — the global sticky banner above the navbar conveys the state. A 503 from `/auth/login` is silently swallowed by the form's catch (no error text, no submit-disable); the user can retry once the global banner clears.

---

## 2. Navigation

### 2.1 NavBar
- Sticky bar at the top of every page except `/login` (sits inside a sticky wrapper shared with `MaintenanceBanner` — see 1.5)
- Left: logo + "PHSAR" text linking to `/`, "Ratings" link, "Watchlist" link, "Add to Library" link → `/library/add`
- Right (when authenticated):
  - **JobBell** (bell icon next to the user button): polls `GET /jobs/mine` every 2s while any of your jobs is queued/running, 30s when idle. Badge count surfaces session-scoped active jobs PLUS unseen-completed jobs since the tab opened (`bellLoginAt` + `bellSeenJobs` set in sessionStorage; cleared on every logout transition via `clearBellSession()` so a relogin in the same tab doesn't inherit the previous session). Clicking opens a dropdown listing up to 5 entries (active + recently-finished); a "View all in Library" tail links to `/library/add` for older jobs. Rendering is JobKind-aware:
    - `user_scrape`: `Add: "<query>"`, stage Fetching → Saving → Done with `items_done/items_total` progress.
    - `backup`: `Backup`, Database icon for the queued state (vs the default Bell), stage Dumping → Verifying backups → Applying retention → Done. On succeeded: `Backup ready (12.4 MB)` substext (using `formatBytes`), or `Re-confirmed existing dump (no new data)` when the create deduped against an existing dump.
    - Failed rows show a friendly error + retry button. Retry is hidden when `result_summary.retryable === false` (permanent failures: `AnimeNotFoundError`, `MainMediaNotFoundError`, `MalIdAlreadyExistsError`, `AnimeFilteredOutError`). Backup-specific error categories (`backup_disk_full`, `backup_corrupt`) render friendly copy instead of the raw stderr — both stay retryable so admin can free space or re-run. While one retry is in flight, every retry button in the dropdown is disabled. Bell stops polling on 401 (token dead).
    - Optimistic-stub pattern: when `/library/add` or the BackupsCard `Create backup` button POSTs, the page pushes a `queued` row into the `optimisticJobs` store with the returned `job_uuid` so the bell renders it instantly without waiting for the next poll. The next `/jobs/mine` fetch reconciles it (UUID match) and replaces the stub with the real row.
    - **Admin pinned reminder**: when the user role is `admin`, the bell also polls `GET /admin/curation/pending-counts` each tick. If `merge + split > 0` the dropdown renders a non-dismissible row at the top (Settings icon, "Admin tasks" title, "N merge, M split pending" detail, chevron-right) linking to `/admin?tab=curation`. The row hover-tints (no idle background) and sits flush against the top corner — `DropdownMenu.Content` is `p-0 overflow-hidden`. The badge contribution counts as "unseen" via the same session-scoped acknowledgment as jobs: `unseenCuration = max(0, totalPending − BELL_CURATION_SEEN_KEY)`. Opening the dropdown snapshots `totalPending` into the sessionStorage key (so the badge clears); resolving a candidate that drops `totalPending` below the snapshot clamps the snapshot down too, so a later-arriving candidate that brings total back up still re-bumps the badge.
    - **Auto-refresh on curation actions**: MergeCandidatesCard and SplitCandidatesCard bump `curationRefresh` (lib/stores/jobs.ts) after a successful merge/dismiss/split/dismiss action (and after a re-detect that flagged new candidates). The bell subscribes via `onBump` and refetches the pending counts in milliseconds — same pattern as `jobsRefresh` / `librarySaved` / `backupSaved`.
  - User button (first letter of username) toggling a dropdown with:
    - User Settings → `/settings`
    - Admin → `/admin` (visible only to admin role)
    - Statistics → `/statistics`
    - Getting Started → `/getting-started`
    - Logout (red) → clears token, redirects to `/login`

### 2.2 Version Footer
- Small muted text at the bottom of every page showing the deployed version.
- When the value looks like a version tag (`v0.13.0`), it's a link to the matching GitHub release; otherwise it's plain text (e.g. `dev` locally).
- Sourced from `PUBLIC_APP_VERSION` at the node runtime.

### 2.3 Route Structure
| Route | Page | Auth Required |
|-------|------|---------------|
| `/` | Home (search bar + placeholders) | Yes |
| `/login` | Login form | No |
| `/register` | Registration form (requires token) | No |
| `/search?q=<token>` | Search results (anime or media view) | Yes |
| `/anime?uuid=<uuid>` | Anime detail (aggregated metadata + media table) | Yes |
| `/media?uuid=<uuid>` | Media detail + rating | Yes |
| `/ratings` | (placeholder) | Yes |
| `/watchlist` | (placeholder) | Yes |
| `/settings` | User preferences (theme, language, rating step, spoiler level, data export, account deletion) | Yes |
| `/library/add` | Add anime via MAL query + recent additions panel | Yes (form disabled for restricted users) |
| `/admin` | Admin sections behind a `?tab=` switcher (Overview / Jobs Log / Tokens / Curation / Backups) | Yes (admin) |
| `/admin/jobs/[uuid]` | Per-job inspection page for update_sweep v2+ rows (per-media field diffs, umbrella reclassifications) | Yes (admin) |
| `/statistics` | (placeholder) | Yes |
| `/getting-started` | (placeholder) | Yes |

---

## 3. Home Page

- **Hero banner** (InfoDiashow): Full-width rounded card showing the active theme's character pic as background (`object-cover`, per-theme focal point). Diagonal gradient overlay fades from the theme's primary color (opaque left) to transparent (right). "Current Season" label and season name (e.g., "Spring 2026") sit on the opaque side with text shadow. Pic and gradient update reactively when user changes theme.
- SearchBar component for entering queries and applying filters
- Three placeholder cards: "Recommended", "Lucky Find", "Upcoming"

---

## 4. Search Flow

### 4.1 Anime/Media View Toggle
- A small pill-shaped toggle sits in the top-right corner of the search page, below the navbar
- Default view: **Anime** (aggregated search grouping media by parent anime)
- Switching toggle: clears all filters and results, reloads filter options for the new view, auto-submits an empty search
- The `view_type` is encoded in the search token, so "Back to search" restores the correct toggle state
- SearchBar placeholder changes: "Search anime..." / "Search media..."

### 4.2 Submitting a Search
1. User types a query in the SearchBar text input
2. Optionally toggles "Expand search to descriptions" checkbox
3. Optionally opens the filter panel and sets filters
4. Submits the form (Enter key)
5. Frontend POSTs filter params (including `view_type`) to `/filters/create-token` → receives a search token
6. Navigates to `/search?q=<token>`

### 4.3 Search Results Page
1. Page reads `q` param from URL
2. POSTs token to `/filters/verify-token` → receives decoded filter params (including `view_type`)
3. View toggle is set to match the decoded `view_type`
4. SearchBar is pre-populated with the decoded filters
5. `GET /search/anime?...` or `GET /search/media?...` fetches results based on view type
6. Results display as cards in a grid
7. "Show More" button loads 20 more results per click
8. If no results: "No results found :-("
9. If no search performed yet: "Start searching!!!"

**Title-query ranking:** Title search starts from embedding cosine similarity, then boosts results whose titles literally contain the query (`Lord of` → `Lord of Mysteries` first, not `Overlord`) and results that fuzzy-match via trigram similarity (typos like `lor of` still surface the intended show near the top). Description and rating-notes search rank by embedding only — those queries are semantic, not literal.

### 4.4 Search Filters
Filters appear in a collapsible panel below the search input. Filter options adapt to the current view type.

**List filters** (searchable tag-select dropdowns, max 5 items each):
- Genres (anime view shows only majority-qualifying genres), Seasons, Studios, Airing Status, Relation Type, Media Type, Age Rating

**Range filters** (dual-thumb sliders):
- Episodes (integer, linear — aggregated sum for anime view)
- Score (decimal, linear)
- Scored By (logarithmic scale — average per media for anime view)
- Average Duration per Episode (time display — hidden in anime view)
- Total Watch Time (time display — aggregated sum for anime view)

**Behavior:**
- Filter options are fetched from `GET /filters/options?view_type=anime|media` on component mount and on view toggle
- "Clear all" button resets all filters and query to defaults
- Modifying filters and resubmitting creates a new search token and navigates
- **Anime view:** filters apply to the value shown on the anime card, not to individual media. Age rating uses the max across media; airing status uses the priority-collapsed value (Currently Airing dominates over Finished over Not yet aired).

---

## 5. Search Result Cards

### 5.1 Media Card (media view)
Each media search result card shows:
- Cover image (lazy-loaded, with fallback; blurred with click-to-reveal when spoiler-protected)
- Title, score + scored-by count, anime season, airing status, age rating
- Genre tags, media type tag, relation type tag
- Total watch time
- Clicking navigates to `/media?uuid=<uuid>` (with `&q=<token>` preserved for back navigation)

### 5.2 Anime Card (anime view)
Each anime search result card shows:
- Cover image (from anime, lazy-loaded with fallback)
- Title, average score + average scored-by ("ratings/media"), season range (e.g., "Spring 2017 - Winter 2024")
- Airing status for active/upcoming anime ("Currently Airing + upcoming content", "Not yet aired", or "upcoming content" for finished anime with announced sequels)
- Age rating (max across media)
- Genre tags (strict majority rule: genre must be on >50% of media)
- Relation type badges with counts (e.g., "Main Story: 5", "Side Story: 2")
- Media type badges with counts (e.g., "TV: 3", "Movie: 1")
- Total watch time (summed across media)
- Clicking navigates to `/anime?uuid=<uuid>` (with `&q=<token>` preserved)

---

## 6. Anime Detail Page

### 6.1 Loading
- Page reads `uuid` param from URL
- Fetches anime detail (`GET /media/anime/{uuid}`)
- While loading: centered "Loading..." pulse animation
- On error: centered red error message

### 6.2 Hero Card
- Same blurred cover background pattern as media detail
- Title (English preferred), alternate titles, airing status badge: green (Currently Airing), yellow (Not yet aired), blue (upcoming content), grey (Finished Airing)
- Average MAL score with "ratings/media" label
- Relation type badges with counts (e.g., "main: 5"), media type badges with counts (e.g., "TV: 3")
- Age rating badge (max across media), genre badges (strict majority rule)
- Stats grid: total episodes, media count, season range, total watch time
- Studio names
- Watchlist bookmark buttons (add all / remove all — stub dialogs, wired in v0.15.0)

### 6.3 Synopsis
- Same collapsible description card as media detail (from anime description)

### 6.4 Media Table
- Compact table with rows for each media in the anime
- Each row: small cover thumbnail (40x56px, blurred when spoiler-protected), title + relation/media type badges, season, score, airing status dot
- Clicking a row navigates to `/media?uuid=<uuid>` (origin params preserved — see 7.6)
- **Select mode**: "Select" button in table header toggles select mode
  - Checkboxes appear on left of each row
  - Clicking rows toggles selection instead of navigating
  - Action bar slides in: "Select all/Deselect all", selected count, "Rate" button, "Watchlist" button
  - "Delete Ratings" button appears when any selected media have existing ratings
  - **Rate** opens BulkRateDialog: score circle + slider, note (applied to last main media), collapsible attributes grid. Overwrite warning shown if any selected media already rated. On save: exits select mode, shows "Note Added" info dialog naming which media received the note.
  - **Delete Ratings** opens a destructive confirmation dialog, then `POST /ratings/bulk-delete`
  - **Watchlist** opens a stub dialog (wired in v0.15.0)
  - "Cancel" exits select mode and clears selection

### 6.5 Ratings Overview ("Your Ratings")
- Appears when the user has rated at least one media in the anime
- **Stats gauge**: Average score displayed in a gauge chart (formatted to 1 decimal), progress bars for media rated / total and episodes watched / total, dropped count badge
- **Rating Timeline**: Bar chart with one bar per media in release order, colored by relation type (Main Story = theme primary, Alt Version = yellow, Side Story = accent red, Summary = secondary green, Crossover = theme ring — a muted shade reserved for the rarest type). Dropped items at 50% opacity. HTML legend showing active relation types. Tooltip shows title, media type, relation type, season, and score.
- **Attribute Summary** (side-by-side on desktop, stacked on mobile):
  - *Quality Radar* (pentagon): 5 quality axes (animation quality, dialogue quality, character depth, story quality, ending quality) normalized to 0–1 scale with 3 split rings. Tooltip shows closest label per axis or "--" for no data. `ending_quality: not_applicable` is excluded from averaging.
  - *Descriptive Pills* (orbital): 6 descriptive attributes (pace, 3D animation, watched format, fan service, ending type, originality) displayed as tilted pills arranged in an elliptical orbit. Each shows "Label: Majority Value" or "--" for no data. Hover straightens and scales the pill. Click triggers a color-burst glow animation cycling through the chart palette.
  - *Collapsible details*: "Show attribute details" toggle expands stacked distribution bars for all 11 attributes. Unrated attributes shown greyed out with "No data" label.
- **Notes**: Collapsible list of user notes per media (first note visible, "Show all N notes" to expand)

### 6.6 Back Navigation
- "Back to search" link appears when `q` search token is present in URL
- Restores the correct anime/media toggle and filters on the search page

---

## 7. Media Detail Page

### 7.1 Loading
- Page reads `uuid` param from URL
- Fetches media detail (`GET /media/{uuid}`) and user rating (`GET /ratings/media/{uuid}`) in parallel
- While loading: centered "Loading..." pulse animation
- On error: centered red error message

### 7.2 Hero Card
- Blurred cover image background with card overlay
- Cover image (with fallback placeholder if missing or load fails; spoiler-guarded with blur + click-to-reveal when media is beyond the spoiler frontier)
- Title (English preferred, falls back to default title)
- Japanese title and romaji subtitle (if different from displayed title)
- Airing status badge: green pulsing dot for "Currently Airing", yellow for "Not yet aired", muted for finished
- MAL score with star icon and rating count
- Badges: media type (green), relation type (blue), age rating (orange)
- Genre badges (themed primary color)
- Stats grid: episodes, duration per episode, season, total watch time
- Studio names
- Disabled bookmark button (placeholder for watchlist, wired in v0.15.0)

### 7.3 Synopsis
- Collapsible description card (4-line clamp by default)
- "Read more" / "Show less" toggle shown only when text actually overflows the 4-line clamp (DOM overflow detection with 2px threshold)
- Synopsis blurred with click-to-reveal when media is spoiler-protected; "Read more" button is behind the blur
- HTML entities cleaned from description text; MAL attribution tags (`[Written by MAL Rewrite]`) and trailing `(Source: …)` / `[Source: …]` attributions stripped before display

### 7.4 Rating Card
- **No rating exists, not editing**: CTA card with star icon and "Rate This" button
- **Restricted users**: Disabled "Rate This" button with "Upgrade your account" message
- **Rating exists, not editing**: Display card showing score circle, dropped/completed status, episodes watched (with total if known), filled attribute badges (ending quality hidden when "Not Applicable"), and note (if any). Edit and Delete buttons.
- **Editing mode** (new or existing):
  - Score: editable circle with direct text input + slider (0-10, step 0.5)
  - Dropped checkbox + episodes watched input (auto-filled with total episodes when not dropped; editable when dropped)
  - Note textarea (max 1000 chars with counter)
  - Collapsible "Details" section with 11 attribute selectors (pace, animation quality, 3D animation, watched format, fan service, dialogue quality, character depth, ending type, ending quality, story quality, originality) — shows set/total count badge. Ending quality: when dropped, auto-set to "Not Applicable" and disabled; when not dropped, only 3 quality options shown (Unsatisfying, Satisfying, Exceptional)
  - Submit/Update button (disabled when no changes detected on existing rating)
  - Cancel button returns to display mode
  - Error message display on save/delete failure
- **API calls**: `PUT /ratings/media/{uuid}` to create/update, `DELETE /ratings/{uuid}` to delete

### 7.5 Related Media Carousel
- Always shown — displays parent anime name as a clickable link to the anime detail page
- If sibling media exist: horizontal scrollable row of compact cards (snap scrolling), **sorted chronologically via the shared `chronological_media_key()` helper** (`(season_year, season_quarter, mal_id)`) — same key as the anime page's media table and the spoiler frontier so the three surfaces never disagree on order
  - Each card: cover image (with fallback; blurred when spoiler-protected), title, media type + relation type badges, season or episode count
  - Clicking a sibling card navigates to that media's detail page (origin params preserved — see 7.6)
  - **"You are here" marker**: a thin primary-colored vertical divider with a small pill label slots into the row at the position the current media occupies in the chronological chain. Backend computes the index (`current_position`) so the frontend doesn't need to compare dates client-side. Position 0 = current is the oldest entry (marker leads the row); position == siblings.length = current is the newest (marker trails the row)
- If no siblings: "No other media in this anime" message

### 7.6 Back Navigation
- Shared `<BackLink>` component (in `lib/components/`) decides which back button to render based on URL params:
  - `?q=<token>` → "Back to search" (search-origin pattern, returns to `/search?q=token`; the token's `view_type` restores the correct anime/media toggle)
  - `?from=library` → "Back to library" (non-search origin used by the recent-additions panel)
  - neither → no back button (direct-URL arrivals stay clean)
- Both flags propagate across the entire anime↔media jump chain (anime → media tile, media → anime link, related-media carousel) via `buildDetailHref`'s options bag, so a deep dive like library → anime → media → sibling stays linkable back to the origin
- Origin set is a closed `DetailOrigin` TS union (`'library'` today); extending it requires updating both `lib/utils/navigation.ts` AND `BackLink.svelte`'s switch — surfaces as a type error otherwise

---

## 8. Settings Page

### 8.1 Theme
- "Theme" card with "Design your lobby" subtitle
- Horizontal scrollable row of theme cards (snap scrolling, `overflow-x-auto`)
- Each card: landscape character pic (`aspect-video`), theme label below, `w-48 sm:w-56`
- Selected theme highlighted with `border-primary ring-2`
- Clicking a card saves immediately via `PUT /users/settings` with `{ theme: key }`
- Selecting a theme changes: app background gradient, login/register background gradient, all primary-colored UI elements (buttons, rings, badges, links, charts), the LoadingScreen sakura-ring color, and the home page hero banner character pic
- Four themes: Default (purple), Crimson (red), Ocean (blue), Forest (green)
- Theme applied via CSS class on `<html>` with localStorage sync for FOUC prevention

### 8.2 Spoiler Protection
- Three-level dropdown: Off, Blur, Hide
- **Off**: No spoiler protection
- **Blur**: "Blur covers and descriptions to avoid spoilers" — media beyond the spoiler frontier are blurred with a "Click to reveal" overlay on covers and descriptions
- **Hide**: "Blur covers and descriptions, and hide spoiler media from search results" — same as blur, plus media search results are filtered to only show visible media
- Spoiler frontier: per anime, all media up to and including the next unwatched **anchor** entry are visible; individually rated media beyond the frontier are also visible. Anchors are `main` AND `alternative_version` — retellings extend the story, so each alt-version gates the next (rating Evangelion TV reveals Rebuild Movie 1 but not Movies 2-4)
- Anime covers and anime-level descriptions are never spoiler-protected
- On detail pages, "hide" mode falls back to blur behavior (user explicitly navigated there)
- Visibility data loaded on auth and refreshed after rating changes
- **Restricted (guest) users**: the spoiler control is disabled and pinned to **Off** — guests can't rate, so a frontier would freeze at episode 1 of every anime and hide the catalogue (they're also excluded from the spoiler-visibility cache). The Rating Step and Data Export controls are likewise shown disabled rather than hidden. Enforced server-side (`PUT /users/settings` drops `spoiler_level` for restricted users)

### 8.3 Account Deletion (Danger Zone)
- Red-bordered "Danger Zone" card at the bottom of the settings page
- Glass overlay covers the entire card; the "Danger Zone" title shows through the tinted glass
- Lock icon and "Click to unlock" prompt centered on the glass
- Each click adds progressive cracks (SVG) with a shake animation; counter shows remaining clicks
- After 5 clicks the glass shatters: 10 shard fragments fly outward with rotation and fade out
- Once broken, the "Delete Account" button is revealed
- **Restricted users**: button is disabled with "You don't have permission to delete your account" message
- Clicking "Delete Account" opens a confirmation dialog requiring the user's current password
- On wrong password: "Invalid password." error below the form
- On success: non-dismissible farewell dialog ("Thank you for using PHSAR...") with "Continue to login" button
- "Continue to login" clears token and settings, redirects to `/login`
- **API call**: `DELETE /users/account` with `{ password }` body

---

## 9. Add to Library Page

### 9.1 Layout
- Two-column card: left is a "Search MAL" form (text input + submit button), right is a "Recently added" panel showing the most recent saved anime across all users (catalog is family-shared, so this is a global feed).
- Restricted users see the page but the form is disabled (`POST /jobs/scrape` rejects them backend-side via `require_user_or_admin` regardless).

### 9.2 Submitting a Scrape Job
- The query must be at least 4 chars (`minlength` attr + button stays disabled until 4 chars typed). MAL's top-3 search is too ambiguous on shorter queries.
- Submitting POSTs `{ query }` to `/jobs/scrape`. Successful enqueue returns 202 with the new job uuid; the form clears and bumps `jobsRefresh` (in `lib/stores/jobs.ts`) so the navbar bell refetches in tens of milliseconds instead of waiting for the next 30s poll.
- 409 dedupe: re-submitting the same normalized query within `JOBS_DEDUPE_HOURS` (default 24) returns "This query is already queued" — failed jobs don't count, so a transient MAL outage doesn't lock the user out for a day.
- 409 per-user cap: more than `JOBS_PER_USER_LIMIT` (default 4) active/queued user jobs returns "You already have 4 active scrape jobs. Wait for one to finish before queueing more."
- 429 daily cap: more than `JOBS_DAILY_LIMIT` (default 50) user_scrape submissions in any trailing 24h window — counts every status, including failed jobs, so a fast-failing client can't cycle through the limit — returns "You've hit your daily limit of 50 anime additions. Please try again tomorrow." Marked permanent so the bell hides retry.
- The job's lifecycle is then surfaced by the navbar bell (see 2.1). Long-term history lives on this page's recent-additions panel rather than the bell, which is intentionally session-scoped.

### 9.3 Recent Additions Panel
- Server-rendered list from `GET /library/recent` returning the most recent anime saved across the catalog (not just this user's scrapes). Each row links to the anime detail page with `?from=library` so the destination renders a "Back to library" button (see 7.6).
- Carries `name_eng` + `name_jap` so the frontend can call `resolveTitle(...)` with the user's `name_language` setting — no second fetch.
- Refreshes automatically when the bell observes a NEW `succeeded` `user_scrape` (bumps `librarySaved` in `lib/stores/jobs.ts`; this panel subscribes via `onBump`). No manual reload required.

---

## 10. Admin Page

### 10.1 Access
- Only accessible to users with `admin` role
- Non-admin users are redirected to `/` on mount
- NavBar dropdown shows "Admin" link only for admin users

### 10.1a Tab navigation
- Admin sections live behind a tab bar driven by the `?tab=` query param (`/admin?tab=overview`, `?tab=jobs`, `?tab=tokens`, `?tab=curation`, `?tab=backups`). Default tab is `overview` if `?tab=` is absent or unknown — a stale bookmark to a retired tab key still lands the admin somewhere useful instead of a blank page.
- The active tab is preserved across refresh and is bookmarkable. Tabs eager-render on first admin load and stay mounted across switches — visibility toggles via `class:hidden`, not conditional unmount. Admin sessions usually touch several tabs in a row, so the one-time parallel-fetch cost on first paint buys instant subsequent switches. No card polls, so keeping them mounted doesn't generate ongoing traffic.

### 10.1b Overview tab (default)
- Four stat cards sourced from `GET /admin/stats/overview`:
  - **Catalog**: total anime count, total media count, anime added in the last 7 days, media added in the last 7 days
  - **Job health (7d)**: per-kind succeeded/failed counts, parenthesized retryable-failed subset, and a colored success-rate percentage (theme-primary at ≥90%, amber at 75–89%, destructive red below 75%). Percent cell is fixed-width + `tabular-nums` so the column edge stays aligned. The `user_scrape` row counts user-initiated submissions only — seasonal-sweep children (system-attributed user_scrapes) are excluded so a Sunday burst of Music/PV-filtered shows doesn't drag the user-facing signal down. Retryable-failed counts ALSO drop system jobs (sweeps, cron backups) since the bell's retry button only fires on user-owned rows; counting cron retries would imply admin action is available when it isn't
  - **Sweep tiers**: where every row sits in the update-sweep cycle, with an **Anime / Media toggle** (default Anime). Four rows in priority cascade — Airing now (emerald) > Stabilizing (amber) > Weekly cycle (sky) > 90-day cycle (indigo). Each row has a horizontal share-of-total bar, count, percentage, and tooltip paraphrasing the predicate (stabilize = first 3 sweeps; 90-day long cycle). The Stabilizing row expands into indented per-check sub-rows ("0 checks / 1 check / …", one per stabilize sweep) showing how the stabilization pipeline is distributed — for media each row is bucketed by its own check count, for anime by its least-settled member. The number of sub-rows tracks the stabilize threshold automatically. The backend exposes these as 4 mutually-exclusive **cycle-membership** buckets at each grain (`AnimeDAO.count_by_sweep_tier_priority` / `count_media_by_sweep_tier_priority` → `sweep_tiers` / `media_sweep_tiers`); the card renders the selected grain 1:1. Membership, not due-ness — a tier counts where a row *belongs* (e.g. "Weekly cycle" = has/is a recent main), so a row doesn't empty itself when a sweep refreshes its members. Sum equals the grain's catalog total (anime count / media count)
  - **User activity (7d)**: active users (distinct user_ids touching ratings or jobs), new ratings, scrapes submitted (user-attributed only)
- Refresh: subscribes to the `librarySaved` bump in `lib/stores/jobs.ts`, so the panel reloads in milliseconds whenever the bell observes a new succeeded `user_scrape` — admin sees the catalog + activity counters move without a manual refresh. No periodic polling
- All counts are aggregate. The Overview tab is leaderboard-free — per-user breakdowns are scoped to the Jobs Log tab where they're needed for debugging
- Cache: none. Admin-only, queries are sub-150ms

### 10.1c Jobs Log tab
- Paginated all-jobs table sourced from `GET /admin/jobs` (50 rows per page, newest-first by `created_at`). Backed by `ix_jobs_created_at_desc` so the default unfiltered scan + COUNT stays cheap as the jobs table grows
- **Clustering**: the default view hides rows whose `parent_job_id` is set, so the list isn't dominated by ~50 system user_scrape children that land after every Sunday's seasonal_sweep. Each `seasonal_sweep` row renders an expander chevron — clicking fetches `?parent_uuid=<UUID>&limit=500` and renders the children inline below the parent, indented with a left primary-tinted border. Re-collapse hides them without re-fetching (state cached per parent). If a sweep ever exceeds the 500-row cap, the expanded view surfaces an amber "Showing X of Y children — rest are older than the 500-row cap" notice rather than silently truncating
- Filters: **Kind** dropdown (All / user_scrape / update_sweep / seasonal_sweep / backup / restore) and **Status** dropdown (All / queued / running / succeeded / failed). Changing either filter resets pagination to page 1 — keeping a stale offset against a narrower filter would strand the admin past the result tail. A monotonic request-id guards against a fast filter-then-page click letting an older response overwrite the newer state
- **Filter persistence**: the active filter is held in an in-session store (not the URL), so it stays applied — and shown in the dropdowns — when switching to another admin tab and back, and when opening a job's detail page and returning via the "← Jobs Log" link. Leaving the admin section entirely (e.g. to Settings) clears it, so re-entering `/admin` starts unfiltered. The filter is not reflected in the URL and does not survive a hard page refresh
- Columns:
  - **Created** — short datetime
  - **Kind** — neutral badge (`User scrape` / `Update sweep` / etc., via shared `formatJobKind`)
  - **Status** — color-coded badge (queued muted, running primary, succeeded emerald, failed destructive)
  - **Duration** — wall-clock seconds since `started_at` (or `started_at → finished_at`). Live-ticks every 1s while any row on the page is `running`; queued rows show `—`. The interval is gated by a `hasRunning` derived so a stable page doesn't keep the timer alive
  - **User** — `requested_by_username` (flattened server-side from the eager-loaded relationship) or `system` for cron + seasonal-sweep children
  - **Detail** — for failed rows, the `error_message` in destructive color; for succeeded rows the dispatcher's `result_summary` rendered per-kind: user_scrape → "+N anime · +M media", update_sweep v5 → "N media refreshed · X media w/ dynamic · Y media w/ static · Z umbrella · W new attached" (v2–v4 use the anime-grained "N touched · X anime w/ dynamic · …"; v1 rows fall back to the legacy "refreshed N anime · M changed · …" copy), seasonal_sweep → "N season entries · M new scrapes enqueued · K already known", backup/restore → filename
- **Click-through to detail page**: rows of kind `update_sweep` with `version >= 2` are clickable (cursor-pointer, hover tint, keyboard-accessible via Enter) — they route to `/admin/jobs/[uuid]` (see 10.1d). Other kinds and pre-v0.14.5 update_sweep rows stay non-clickable since the detail page has nothing to add beyond what the row already shows
- **Unknown-genre-tag highlight**: update_sweep v3 rows whose `result_summary.unknown_genre_tags` is non-empty get an amber tint + a left amber accent border + an inline subline under the payload summary listing the missing tag names ("⚠ New genre tags need seeding: Survival Game, Dark Fantasy"). The seeder is the deliberate source of truth for the user-facing genre taxonomy, so unknown tags don't auto-seed — they surface here for admin to add manually before the next sweep
- Pagination footer: `"start–end of total"` range on the left, prev/next buttons + `"Page N of M"` on the right. Buttons disable at the boundaries. `total === 0` degrades to `"0 of 0"` and both buttons disabled
- Tab eager-renders on first admin paint (visibility toggles via `class:hidden`, not unmount) — first paint pays one filtered COUNT + SELECT alongside the other tabs' fetches, subsequent tab switches are instant

### 10.1d Job detail page (`/admin/jobs/[uuid]`)
- Standalone route (not a tab — a separate SvelteKit page). Reached by clicking an `update_sweep v2+` row in the Jobs Log. Direct-URL access works too; admin role is enforced on mount (non-admin → `/`)
- **Header card**: kind badge, color-coded status badge, version chip (`v3`), duration (live-ticks for running jobs), created / started / finished timestamps, requested_by username, parent-job link if `parent_job_uuid` is set, "← Jobs Log" back link. Failed jobs render the `error_message` in a destructive-tinted banner below the metadata grid — this is the actionable info, the page omits the "predates v0.14.5" notice for failed rows since their missing counters reflect a crashed run, not an old schema
- **Counters grid** (v2+ jobs only): version-aware stats from `result_summary.counters`. v5 (v0.14.8, media-level) shows media refreshed, anime touched, media skipped (media belonging to touched anime not refreshed this run — tooltip), media w/ dynamic changes, media w/ static changes, umbrella reclassed, probes succeeded, probes failed, anime w/ new attach, orphaned studios removed, failed refresh. v2–v4 show the original anime-grained set (anime refreshed + anime w/ dynamic/static rollups instead of the media-level trio). The "Failed refresh" cell renders "—" for v<4 (not a misleading 0) and tints amber when > 0. Plus inline warning lines if `merge_detect_failed` or `cache_recompute_failed` fired (the catalog work still committed; only the post-sweep merge-detection / spoiler-cache recompute failed)
- **Failed-refresh / Failed-probe cards**: when `step1_failures` (v4+) or `probe_failures` (v5+) is non-empty, a card lists each skipped anime — title (link to `/anime?uuid=<uuid>`), `error_category` chip, and the error message. Both kept their old `last_checked_at` / `AnimeFreshness`, so the next sweep retries them. A progress-divergence notice fires when `items_done < items_total` — v5 progress is media-grained (`items_total` = due media, `items_done` = refreshed media), so the gap is the media skipped because their anime failed step-1 refresh (probe failures don't widen it — their media committed; they show in the Failed-probe card). v2–v4 rows keep the anime-grained wording
- **Media changes section** (v2+ only): filter chips (All / Dynamic-no-rating / Rating only / Static only / Has genre-studio drift) + free-text search input (substring match across `media_title`, `media_name_eng`, `media_name_jap`, `anime_title`, `anime_name_eng`, `anime_name_jap`, `media_mal_id`). Each match renders a `MediaChangeCard` — media title links to `/media?uuid=<uuid>` (new tab), relation-type chip, mal_id, and a Field/Was/Now table with one row per changed field. Tone colors via a left border: rating (gray, score/scored_by — sorts last so vote-count noise doesn't drown the rest), dynamic (amber, episodes/airing/aired_to), static (sky), genre (fuchsia), studio (indigo). Genre / studio drift folds into the same table as a tagset row — was-cell shows old tags with removed in red, now-cell shows new tags with added in green. v2 legacy drift kinds render a "Not auto-applied — admin review needed" subline beneath the now-cell since the dispatcher only logged them; v3 drift is always applied (audit log is the rollback path)
- **Anime field changes section** (v2+ only) — heading "Anime field changes": for each anime whose 7 aggregate fields drifted, an `AnimeUmbrellaCard` shows the anime title (link to `/anime?uuid=<uuid>`, new tab), "anchor moved" / "embedding regen" badges when applicable, a Field/Was/Now table for the changed umbrella fields, and a list of per-media relation reclassifications (`mal_id=NNNN: old_rt → new_rt`)
- **v1 fallback**: pre-v0.14.5 sweeps (job version 1) didn't capture per-media diffs. The page renders the header + a "predates v0.14.5's per-media diff capture" notice in place of the counters/diff sections. v1 rows are NOT clickable from the Jobs Log so this fallback is reached only via direct URL

### 10.2 Create Registration Token (Tokens tab)
- Form with role selector (User / Restricted User) and expiry dropdown (1 day / 7 days / 30 days)
- "Create" button POSTs to `/admin/registration-tokens`
- On success: token string shown in a highlighted banner with copy button and toast feedback
- Changing the role or expiry selector dismisses the success banner

### 10.3 Token List
- Card title shows the live count: `Registration Tokens (N)`.
- Displays all registration tokens with: truncated token (click to copy), status badge (active/used/expired), role badge, creation date, and either an expiry date (active/expired tokens) or a "Used &lt;date&gt; by &lt;username&gt;" line (used tokens — once consumed, the expiry date is no longer the useful piece of info, so it's replaced with the consumption date)
- **Sort options** (dropdown): By Status (default: active → used → expired), Newest First, Expiring Soon (active tokens first by soonest expiry), Recently Used
- **Delete**: trash icon on unused/expired tokens opens confirm/cancel inline buttons. Used tokens cannot be deleted. DELETE returns 204.

### 10.4 Backups (Backups tab)
- Card title shows the live count: `Backups (N)`.
- **Create backup**: POST returns 202 with `{job_uuid}` instead of running pg_dump synchronously. The button shows a toast ("Backup queued. We'll let you know when it's ready.") and disables for 5 seconds to absorb double-clicks. The bell shows a queued row instantly (optimistic stub seeded from the returned uuid; see 2.1) and tracks the job through to completion. When the job succeeds the bell bumps `backupSaved`; this card subscribes via `onBump` and refetches the dump list, so the new row appears with a green `ok` integrity badge and a source badge (`Manual`, `Scheduled`, `Pre-restore`, or `Upload`) without any manual reload. Cron-triggered backups stay system jobs (invisible to every bell) — they appear in this list on the card's next mount or sort change.
- **Upload**: file input accepts `.dump` files; `/admin/backups/upload` runs `pg_restore -f -` to validate + compute a content hash that ignores per-run timestamps and psql `\restrict` tokens. An upload whose DB state matches an existing dump returns 409 ("identical to `<filename>`"). Uploads never move the "Current" badge — uploaded bytes are external and the backend can't verify they match live DB.
- **List**: filename, timestamp, human-readable size, integrity badge, source badge. A named dump shows its name above the filename plus an amber "Pinned" badge. The dump whose content matches the live DB gets a blue "Current" badge (git-branch icon) and a faint blue tint on the row — this is the dump the last restore left, or (when a create dedupes) the pre-existing dump it re-confirmed, or (in the normal create path) the just-created dump itself. Deleting the current dump clears the marker so the badge disappears.
  - The `is_current` row, when the live state came from a restore, shows a "Previous state saved as `<pre-restore filename>`" line. A `pre_restore` row shows "Snapshot of the state before restoring `<filename>`". Both come from sidecar metadata (the restore stamps the pre-restore snapshot's `restored_to`).
- **Rename / pin**: pencil icon opens an inline name field (Save / Cancel). A non-empty name pins the dump so auto-retention never deletes it (admin actively chose to keep it); the row then shows a "Pinned" badge. A pinned dump shows a one-click pin-off button directly in its row (no edit mode needed) that clears the name and unpins; saving a blank name in the editor does the same. `PATCH /admin/backups/{filename}` with `{name}`. Pinned dumps are kept on top of the normal rolling window — they don't consume the 14-recent / Sunday / cap slots.
- **Sort options** (dropdown): Newest First (default), Oldest First, Largest First, By Integrity (corrupt/unknown first to surface problems). In "Newest First" only, the Current row is pinned to the top regardless of its age — so a post-restore older dump stays salient as "what's live right now". Other sorts respect their natural order.
- **Download**: arrow icon per row uses the `downloadBlob` helper (bearer token via fetch headers, then auto-click on an object URL). Saved with the original filename.
- **Restore**: rotate-back icon opens a destructive-confirm dialog that requires typing the admin's username. Disabled on `corrupt` rows. Backend auto-snapshots as a `pre-restore` dump *before* entering maintenance mode, then flips the maintenance flag, closes the SQLAlchemy pool, terminates any other DB sessions, and runs `pg_restore --clean --if-exists` (timeout configurable via `BACKUP_RESTORE_TIMEOUT_SECONDS`, default 10 min). After pg_restore returns, the backend warms the connection pool before lifting the maintenance gate so the first post-restore request doesn't flap the liveness probe. Result banner reports the pre-restore filename, and the "Current" badge now follows the restored dump. The pre-restore snapshot's `restored_to` is stamped to the restored dump, so the restored (now-current) row shows "Previous state saved as …" and the pre-restore tied to the current state is retention-pinned (kept until a later restore supersedes it). All non-admin users in the app are bounced to `/login` for the duration; the sticky global banner conveys the maintenance state (see 1.5).
- **Delete**: trash icon opens inline confirm/cancel buttons. DELETE returns 204.

### 10.5 Merge Candidates (Curation tab)
- Card title shows the live count: `Merge Candidates (N)`.
- Admin-only.
- **List**: pending merge candidates flagged by the duplicate detector (running on every save covering new × new and new × existing pairs, at app startup covering existing × existing, and on admin demand via the Re-run detection button). Each row shows:
  - A "% match" badge (similarity score)
  - A `detected_by` label (`title_studio`, `title_desc`, or `relation_link`)
  - Side-by-side anime cards labelled "Anime A (kept)" / "Anime B (merged in)" with title, romanized name, year, media count, rating count, and primary studio names. The recommended A is whichever side has the earliest aired media (with rating count as tiebreak); rating count is shown explicitly so the admin can see the justification.
  - Anime titles link to `/anime?uuid=<uuid>` (open in new tab) for context before deciding
  - **Reclassification preview** (when the merge would change any media's relation type): a "Pending reclassifications" sub-block lists the per-media diffs (`old_relation_type → new_relation_type`) that would land if A absorbed B. Surfaces substance-gate demotions, alt-version labels, and anchor flips so the admin sees the structural impact before clicking merge.
- **Swap A/B**: per-row ghost button next to the similarity badge. Flips which side is rendered as A vs B and changes which uuid is sent as `keep_uuid` on merge. Local-only state; refresh resets the toggles.
- **Refresh**: spinning-arrow icon in the header re-fetches the list silently — existing rows stay rendered while the request is in flight, the spinner spins, and the keyed each-block diffs the result in place. The list never collapses to "Loading…" mid-refresh, so there's no scroll jump.
- **Re-run detection**: magnifying-glass icon next to the refresh control. Re-runs the existing × existing detection backfill on demand — primarily for the post-restore workflow (restore doesn't bounce the container, so the lifespan-startup backfill never sees the restored catalog). The backfiller is idempotent: already-flagged pairs (any status) skip via `seen_pairs`, so repeat clicks return 0. Shows a "Flagged N new candidate(s)" inline note on success.
- **Merge**: re-parents B's media onto A and deletes B (cascade-removes the candidate row + any other pending pairs referencing B). A's anime embedding is regenerated, the duplicate detector re-runs against the survivor (so freshly-valid pairs from the merged-in media surface as new candidates), and the spoiler-cache is recomputed for all users. Merge button opens an inline confirm/cancel pair; while in flight the button shows "Merging…" and the row stays visible. On success the list refetches automatically (silent), so cascade-resolved rows leave and any re-detected pairs appear in one update. Backend rejects with 409 if A and B share any `Media.mal_id` (a should-never-happen invariant; admin investigates manually).
- **Dismiss**: marks the candidate `dismissed` (status flip; row stays in DB so the seen-pairs filter prevents re-flagging). Same inline confirm/cancel UX. On success the row is removed from the local list.
- Merge / dismiss / re-detect-with-new-rows all bump `curationRefresh` (lib/stores/jobs.ts) so the navbar bell's pinned admin reminder + badge contribution refresh in milliseconds.
- Already-resolved candidates (merged or dismissed) return 409 if the action is retried.
- The detector itself is invisible to non-admin users; nothing about it surfaces outside this card.

### 10.6 Split Candidates (Curation tab)
- Card title shows the live count: `Split Candidates (N)`.
- Stacked below Merge Candidates on the same Curation tab. Admin-only.
- **List**: pending split candidates flagged by `find_disjoint_franchises`, which finds substance-passing media inside one anime row that form their own connected sequel chain — the BNHA↔Vigilante, Toaru Index↔Railgun, Pretty Rhythm↔(PriPara/King of Prism/Pri☆chan/AiPri) shapes. Detection runs on every save (scrape-time), inside the relation-backfiller's per-anime loop (lifespan startup + admin re-trigger), AND after every merge survivor reclassify (so a merge that surfaces previously-dangling bridges gets flagged). Each row shows:
  - A `N cluster(s)` badge (count of disjoint sub-franchises detected under this anime)
  - A `detected_by` label (`scrape`, `backfill`, `merge_survivor`, `post_split_source`, `post_split_new`)
  - **Source anime card** with title, romanized name, year, media count, rating count, primary studios (same shape as the Merge Candidates A/B card)
  - **Expandable cluster preview**: a chevron-button reveals the per-cluster member list (mal_id, title, media_type, current relation_type) plus the suggested anchor mal_id and bridge-edge labels (the MAL relations that absorbed this cluster into the parent — typically `spin-off`, `parent_story`, or none-if-orphan)
- **Refresh**: spinning-arrow icon — same silent-refresh pattern as Merge Candidates (keyed each-block diffs in place, no scroll jump).
- **Re-run detection**: magnifying-glass icon. Re-runs `backfill_split_candidates` across the catalog on demand. Idempotent via cluster-signature supersede: if the payload matches an already-pending row, no insert; if the payload changed (new media absorbed since detection), the old pending row is auto-dismissed and a fresh one is inserted. Shows a "Flagged N new candidate(s)" inline note on success.
- **Split**: creates one new Anime row per detected cluster, re-parents the cluster's Media rows under the new anime (Media UUIDs are stable so any existing Ratings stay attached), reclassifies both the source and each new anime, then runs merge detection over the newly-split-out rows. The source anime's umbrella may shift if the smaller media set picks a different anchor. Inline confirm/cancel pair; while in flight the button shows "Splitting…" and the row stays visible. On success the list refetches silently and an inline note reports the number of new anime rows created.
- **Dismiss**: marks the candidate `dismissed` (status flip; row stays in DB so the cluster-signature supersede in the DAO doesn't re-flag the same shape on next detection). Same inline confirm/cancel UX. On success the row is removed from the local list.
- Split / dismiss / re-detect-with-new-rows all bump `curationRefresh` so the navbar bell's pinned reminder updates without waiting for the next poll tick.
- Already-resolved candidates (split or dismissed) return 409 if the action is retried.
- **Stale-candidate fail-loud**: if the classifier on the cluster subset picks a different anchor than the candidate's `suggested_anchor_mal_id` at execute time (e.g., MAL added a sequel between detection and execution), the backend returns 409 SplitCandidateStaleError. Admin re-runs detection to refresh the payload.
- The detector itself is invisible to non-admin users; nothing about it surfaces outside this card.

---

## 11. API Endpoints Used by Frontend

| Endpoint | Method | When |
|----------|--------|------|
| `/auth/login` | POST | Login form submission |
| `/auth/validate` | GET | Every page load (layout) |
| `/filters/options?view_type=anime\|media` | GET | SearchBar mount and view toggle |
| `/filters/create-token` | POST | Search submission |
| `/filters/verify-token` | POST | Search page load |
| `/search/anime` | GET | Anime-view search after token verification |
| `/search/media` | GET | Media-view search after token verification |
| `/media/anime/{uuid}` | GET | Anime detail page load |
| `/media/{uuid}` | GET | Media detail page load |
| `/ratings/media/{uuid}` | GET | Media detail page load (fetch user's rating) |
| `/ratings/anime/{uuid}` | GET | Anime detail page load (fetch user's ratings for all media) |
| `/ratings/media/{uuid}` | PUT | Create or update a rating |
| `/ratings/bulk` | PUT | Bulk rate selected media from anime detail |
| `/ratings/bulk-delete` | POST | Bulk delete ratings from anime detail |
| `/ratings/{uuid}` | DELETE | Delete a rating |
| `/ratings/spoiler-visibility` | GET | Layout auth (fetch visible media UUIDs for spoiler protection) |
| `/users/settings` | GET | Layout auth (fetch user settings) |
| `/users/settings` | PUT | Settings page (update preferences) |
| `/users/export?format=json\|csv` | GET | Settings page (data export download — flat media-level rows, filename includes username + date) |
| `/users/account` | DELETE | Settings page (account deletion with password) |
| `/admin/stats/overview` | GET | Admin Overview tab (aggregate catalog + job health + activity counters) |
| `/admin/jobs` | GET | Admin Jobs Log tab (paginated all-jobs list with status/kind/user/date filters) |
| `/admin/curation/pending-counts` | GET | Polled by JobBell each tick when user role is admin; drives the pinned reminder + badge contribution |
| `/admin/registration-tokens` | GET | Admin page (list all tokens) |
| `/admin/registration-tokens` | POST | Admin page (create token) |
| `/admin/registration-tokens/{uuid}` | DELETE | Admin page (delete unused token) |
| `/admin/backups` | GET | Admin page Backups card (list dumps) |
| `/admin/backups` | POST | Admin page Backups card "Create backup" — enqueues a `backup` job and returns 202; bell tracks progress, dump list auto-refreshes on succeeded |
| `/admin/backups/{filename}` | GET | Admin page Backups card (download dump) |
| `/admin/backups/{filename}` | DELETE | Admin page Backups card (delete dump) |
| `/admin/backups/{filename}` | PATCH | Admin page Backups card (rename / pin a dump; blank name unpins) |
| `/admin/backups/{filename}/restore` | POST | Admin page Backups card (restore with username confirm; backend auto-takes a pre-restore snapshot) |
| `/admin/backups/upload` | POST | Admin page Backups card (multipart upload of a `.dump` file) |
| `/admin/merge-candidates` | GET | Admin page Merge Candidates card (list pending duplicates) |
| `/admin/merge-candidates/{uuid}/merge` | POST | Admin page Merge Candidates card (merge B into A, delete B) |
| `/admin/merge-candidates/{uuid}/dismiss` | POST | Admin page Merge Candidates card (mark as reviewed-not-duplicate) |
| `/admin/merge-candidates/backfill` | POST | Admin page Merge Candidates card "Re-run detection" — re-runs existing × existing detection without a container restart (post-restore workflow) |
| `/admin/split-candidates` | GET | Admin page Split Candidates card (list pending disjoint-franchise rows) |
| `/admin/split-candidates/{uuid}/split` | POST | Admin page Split Candidates card (split clusters into separate anime, re-parent media) |
| `/admin/split-candidates/{uuid}/dismiss` | POST | Admin page Split Candidates card (mark as reviewed-keep-bundled) |
| `/admin/split-candidates/backfill` | POST | Admin page Split Candidates card "Re-run detection" — re-runs disjoint-franchise detection across the catalog |
| `/auth/register` | POST | Registration page |
| `/maintenance/status` | GET | Polled by MaintenanceBanner every 30s on every page (no auth) |
| `/jobs/scrape` | POST | `/library/add` form submission (enqueues a `user_scrape` job; restricted users rejected by role check) |
| `/jobs/mine` | GET | Polled by JobBell every 2s while any of your jobs is queued/running, every 30s when idle (active + recently-finished jobs for the current user) |
| `/jobs/{uuid}` | GET | Single-job poll for owner or admin (used by bell retry + admin debugging) |
| `/library/recent` | GET | `/library/add` recent-additions panel (global feed of recently-saved anime) |
| `/admin/jobs/schedule-sweep` | POST | Coolify cron only — bearer token authenticated, enqueues a delayed `update_sweep` |
| `/admin/jobs/schedule-seasonal` | POST | Coolify cron only — bearer token authenticated, enqueues a delayed `seasonal_sweep` |
| `/admin/jobs/schedule-nightly` | POST | Coolify cron only — bearer token authenticated, combined daily entry: enqueues `backup` (immediate) + delayed `update_sweep` + (Sundays UTC) delayed `seasonal_sweep` |

---

## 12. Error States

| Scenario | Expected Behavior |
|----------|-------------------|
| Login with wrong credentials | Red error message below form |
| Login network failure | "An unexpected error occurred." |
| Expired/invalid token on page load | Redirect to `/login` |
| Search API failure | Red error message on search page |
| Filter options fetch failure | Logged to console, search still works |
| Media detail load failure | Red error message centered on page |
| Rating save failure | Red error message below rating form |
| Rating delete failure | Red error message below rating card |
| Rating fetch returns 404 | No rating displayed (expected for unrated media) |
| Account deletion wrong password | "Invalid password." error below form |
| Account deletion network failure | "Failed to delete account." error below form |
| Any API call returns 503 `{maintenance: true}` | Token cleared, `maintenanceRefresh` bumped (so the global banner refetches in ms), hard-navigate to `/login` if not already there. The sticky global banner conveys the state. |
| `/auth/login` during maintenance | 503 silently swallowed by the form catch (no inline error). The global banner is the only signal. Submit not disabled, retry later. |
| Duplicate backup upload | 409 "This dump is identical to an existing backup: '<filename>'." — the new upload is discarded |
| Backup upload >2 GB | 413 "Uploaded backup is too large: <N> MB (limit: 2048 MB)." — partial file discarded |
| Restore of a corrupt dump | Restore button is disabled on rows with integrity badge = corrupt |
