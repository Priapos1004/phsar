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
- Clicking "Logout" in the NavBar dropdown triggers a ~1.5s themed sakura-ring loading screen, then clears the token and redirects to `/login`
- Involuntary logouts (401 from API, token expiry, account deletion) skip the animation and redirect instantly

### 1.4 Token Persistence
- Token is stored in and loaded from localStorage
- Closing and reopening the browser keeps the user logged in (until token expires or is invalidated)

### 1.5 Maintenance Banner
- When the backend returns 503 with `{maintenance: true}` on *any* request, the API client clears the token and hard-navigates to `/login?maintenance=1`.
- The login page also detects this state when `/auth/login` itself returns 503.
- Yellow banner above the form: "Backup restore in progress. Login will be available again once it completes."
- Submit is not disabled; retrying during the window repopulates the banner. On a successful login the banner clears and the user proceeds to `/` as normal.

---

## 2. Navigation

### 2.1 NavBar
- Sticky bar at the top of every page except `/login`
- Left: logo + "PHSAR" text linking to `/`, "Ratings" link, "Watchlist" link
- Right (when authenticated): user button (first letter of username) toggling a dropdown with:
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
| `/admin` | Registration token management (admin only) | Yes (admin) |
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
- Clicking a row navigates to `/media?uuid=<uuid>` (with search token preserved)
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
- **Rating Timeline**: Bar chart with one bar per media in release order, colored by relation type (Main Story = purple, Summary = green, Crossover = yellow, Side Story = red). Dropped items at 50% opacity. HTML legend showing active relation types. Tooltip shows title, media type, relation type, season, and score.
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
- If sibling media exist: horizontal scrollable row of compact cards (snap scrolling)
  - Each card: cover image (with fallback; blurred when spoiler-protected), title, media type + relation type badges, season or episode count
  - Clicking a sibling card navigates to that media's detail page (search token preserved)
- If no siblings: "No other media in this anime" message

### 7.6 Back Navigation
- "Back to search" link appears when `q` search token is present in URL
- Search token is preserved across the entire navigation chain: search → anime → media → sibling media → back to search
- Token includes `view_type`, so returning to search restores the correct anime/media toggle

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
- Spoiler frontier: per anime, all media up to and including the next unwatched main-story entry are visible; individually rated media beyond the frontier are also visible
- Anime covers and anime-level descriptions are never spoiler-protected
- On detail pages, "hide" mode falls back to blur behavior (user explicitly navigated there)
- Visibility data loaded on auth and refreshed after rating changes

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

## 9. Admin Page

### 9.1 Access
- Only accessible to users with `admin` role
- Non-admin users are redirected to `/` on mount
- NavBar dropdown shows "Admin" link only for admin users

### 9.2 Create Registration Token
- Form with role selector (User / Restricted User) and expiry dropdown (1 day / 7 days / 30 days)
- "Create" button POSTs to `/admin/registration-tokens`
- On success: token string shown in a highlighted banner with copy button and toast feedback
- Changing the role or expiry selector dismisses the success banner

### 9.3 Token List
- Displays all registration tokens with: truncated token (click to copy), status badge (active/used/expired), role badge, creation date, expiry date, used-by username
- **Sort options** (dropdown): By Status (default: active → used → expired), Newest First, Expiring Soon (active tokens first by soonest expiry), Recently Used
- **Delete**: trash icon on unused/expired tokens opens confirm/cancel inline buttons. Used tokens cannot be deleted. DELETE returns 204.

### 9.4 Backups
- Card below the token list. Admin-only.
- **Create backup**: POSTs to `/admin/backups`; new dump appears in the list with a green `ok` integrity badge and a source badge (`Manual`, `Scheduled`, `Pre-restore`, or `Upload`).
- **Upload**: file input accepts `.dump` files; `/admin/backups/upload` runs `pg_restore -f -` to validate + compute a content hash that ignores per-run timestamps and psql `\restrict` tokens. An upload whose DB state matches an existing dump returns 409 ("identical to `<filename>`") and re-points the "Current" badge at the existing dump.
- **List**: filename, timestamp, human-readable size, integrity badge, source badge. The dump whose content matches the live DB gets a blue "Current" badge (git-branch icon) and a faint blue tint on the row — this is the last-restored dump, or (when a create/upload dedupes) the pre-existing dump it re-confirmed. Deleting the current dump clears the marker so the badge disappears.
- **Sort options** (dropdown): Newest First (default), Oldest First, Largest First, By Integrity (corrupt/unknown first to surface problems).
- **Download**: arrow icon per row uses the `downloadBlob` helper (bearer token via fetch headers, then auto-click on an object URL). Saved with the original filename.
- **Restore**: rotate-back icon opens a destructive-confirm dialog that requires typing the admin's username. Disabled on `corrupt` rows. Backend auto-snapshots as a `pre-restore` dump *before* entering maintenance mode, then flips the maintenance flag, closes the SQLAlchemy pool, terminates any other DB sessions, and runs `pg_restore --clean --if-exists` (timeout configurable via `BACKUP_RESTORE_TIMEOUT_SECONDS`, default 10 min). After pg_restore returns, the backend warms the connection pool before lifting the maintenance gate so the first post-restore request doesn't flap the liveness probe. Result banner reports the pre-restore filename, and the "Current" badge now follows the restored dump. All non-admin users in the app are bounced to `/login?maintenance=1` for the duration (see 1.5).
- **Delete**: trash icon opens inline confirm/cancel buttons. DELETE returns 204.

---

## 10. API Endpoints Used by Frontend

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
| `/admin/registration-tokens` | GET | Admin page (list all tokens) |
| `/admin/registration-tokens` | POST | Admin page (create token) |
| `/admin/registration-tokens/{uuid}` | DELETE | Admin page (delete unused token) |
| `/admin/backups` | GET | Admin page Backups card (list dumps) |
| `/admin/backups` | POST | Admin page Backups card (create dump on demand) |
| `/admin/backups/{filename}` | GET | Admin page Backups card (download dump) |
| `/admin/backups/{filename}` | DELETE | Admin page Backups card (delete dump) |
| `/admin/backups/{filename}/restore` | POST | Admin page Backups card (restore with username confirm; backend auto-takes a pre-restore snapshot) |
| `/admin/backups/upload` | POST | Admin page Backups card (multipart upload of a `.dump` file) |
| `/auth/register` | POST | Registration page |

---

## 11. Error States

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
| Any API call returns 503 `{maintenance: true}` | Token cleared, hard-navigate to `/login?maintenance=1`, yellow banner displayed |
| `/auth/login` during maintenance | 503 shows the same yellow banner; submit not disabled, retry later |
| Duplicate backup upload | 409 "This dump is identical to an existing backup: '<filename>'." — the new upload is discarded |
| Backup upload >2 GB | 413 "Uploaded backup is too large: <N> MB (limit: 2048 MB)." — partial file discarded |
| Restore of a corrupt dump | Restore button is disabled on rows with integrity badge = corrupt |
