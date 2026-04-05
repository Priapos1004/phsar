# User Flows — Test Specification

This document describes the user-facing behavior of the PHSAR frontend. It serves as the source of truth for what should still work after the shadcn/runes migration.

---

## 1. Authentication

### 1.1 Login
- User sees a centered card with username/password fields and a "Login" button
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
- Clicking "Logout" in the NavBar dropdown clears the token and redirects to `/login`

### 1.4 Token Persistence
- Token is stored in and loaded from localStorage
- Closing and reopening the browser keeps the user logged in (until token expires or is invalidated)

---

## 2. Navigation

### 2.1 NavBar
- Sticky bar at the top of every page except `/login`
- Left: logo + "PHSAR" text linking to `/`, "Ratings" link, "Watchlist" link
- Right (when authenticated): user button ("U") toggling a dropdown with:
  - User Settings → `/settings`
  - Statistics → `/statistics`
  - Getting Started → `/getting-started`
  - Logout (red) → clears token, redirects to `/login`

### 2.2 Route Structure
| Route | Page | Auth Required |
|-------|------|---------------|
| `/` | Home (search bar + placeholders) | Yes |
| `/login` | Login form | No |
| `/search?q=<token>` | Search results | Yes |
| `/media?uuid=<uuid>` | Media detail + rating | Yes |
| `/ratings` | (placeholder) | Yes |
| `/watchlist` | (placeholder) | Yes |
| `/settings` | (placeholder) | Yes |
| `/statistics` | (placeholder) | Yes |
| `/getting-started` | (placeholder) | Yes |

---

## 3. Home Page

- Displays current anime season (e.g., "Spring 2026") via InfoDiashow
- SearchBar component for entering queries and applying filters
- Three placeholder cards: "Recommended", "Lucky Find", "Upcoming"

---

## 4. Search Flow

### 4.1 Submitting a Search
1. User types a query in the SearchBar text input
2. Optionally toggles "Expand search to descriptions" checkbox
3. Optionally opens the filter panel and sets filters
4. Submits the form (Enter key)
5. Frontend POSTs filter params to `/filters/create-token` → receives a search token
6. Navigates to `/search?q=<token>`

### 4.2 Search Results Page
1. Page reads `q` param from URL
2. POSTs token to `/filters/verify-token` → receives decoded filter params
3. SearchBar is pre-populated with the decoded filters
4. `GET /search/media?...` fetches results with all filter params as query string
5. Results display as cards in a grid
6. "Show More" button loads 20 more results per click
7. If no results: "No results found :-("
8. If no search performed yet: "Start searching!!!"

### 4.3 Search Filters
Filters appear in a collapsible panel below the search input.

**List filters** (searchable tag-select dropdowns, max 5 items each):
- Genres, Seasons, Studios, Airing Status, Relation Type, Media Type, Age Rating

**Range filters** (dual-thumb sliders):
- Episodes (integer, linear)
- Score (decimal, linear)
- Scored By (logarithmic scale)
- Average Duration per Episode (time display)
- Total Watch Time (time display)

**Behavior:**
- Filter options are fetched from `GET /filters/options` on component mount
- "Clear all" button resets all filters and query to defaults
- Modifying filters and resubmitting creates a new search token and navigates

---

## 5. Media Card Display

Each search result card shows:
- Cover image (lazy-loaded, with fallback)
- Title
- Score + scored-by count
- Anime season
- Airing status
- Age rating
- Genre tags
- Media type tag
- Relation type tag
- Total watch time
- Bookmark/watchlist indicator icon
- Clicking a card navigates to `/media?uuid=<uuid>` (with `&q=<token>` preserved for back navigation)

---

## 6. Media Detail Page

### 6.1 Loading
- Page reads `uuid` param from URL
- Fetches media detail (`GET /media/{uuid}`) and user rating (`GET /ratings/media/{uuid}`) in parallel
- While loading: centered "Loading..." pulse animation
- On error: centered red error message

### 6.2 Hero Card
- Blurred cover image background with card overlay
- Cover image (with fallback placeholder if missing or load fails)
- Title (English preferred, falls back to default title)
- Japanese title and romaji subtitle (if different from displayed title)
- Airing status badge: green pulsing dot for "Currently Airing", yellow for "Not yet aired", muted for finished
- MAL score with star icon and rating count
- Badges: media type (green), relation type (blue), age rating (orange)
- Genre badges (purple)
- Stats grid: episodes, duration per episode, season, total watch time
- Studio names
- Disabled bookmark button (placeholder for watchlist, wired in v0.15.0)

### 6.3 Synopsis
- Collapsible description card (4-line clamp by default)
- "Read more" / "Show less" toggle for descriptions over 300 characters
- HTML entities cleaned from description text

### 6.4 Rating Card
- **No rating exists, not editing**: CTA card with star icon and "Rate This" button
- **Restricted users**: Disabled "Rate This" button with "Upgrade your account" message
- **Rating exists, not editing**: Display card showing score circle, dropped/completed status, episodes watched (with total if known), filled attribute badges, and note (if any). Edit and Delete buttons.
- **Editing mode** (new or existing):
  - Score: editable circle with direct text input + slider (0-10, step 0.5)
  - Dropped checkbox + episodes watched input (auto-filled with total episodes when not dropped; editable when dropped)
  - Note textarea (max 1000 chars with counter)
  - Collapsible "Details" section with 11 attribute selectors (pace, animation quality, 3D animation, watched format, fan service, dialogue quality, character depth, ending type, ending quality, story quality, originality) — shows set/total count badge
  - Submit/Update button (disabled when no changes detected on existing rating)
  - Cancel button returns to display mode
  - Error message display on save/delete failure
- **API calls**: `PUT /ratings/media/{uuid}` to create/update, `DELETE /ratings/{uuid}` to delete

### 6.5 Related Media Carousel
- Always shown — displays parent anime name as context
- If sibling media exist: horizontal scrollable row of compact cards (snap scrolling)
  - Each card: cover image (with fallback), title, media type + relation type badges, season or episode count
  - Clicking a sibling card navigates to that media's detail page
- If no siblings: "No other media in this anime" message

### 6.6 Back Navigation
- "Back to search" link appears when `q` search token is present in URL
- Preserves search context when navigating from search results to media detail and back

---

## 7. API Endpoints Used by Frontend

| Endpoint | Method | When |
|----------|--------|------|
| `/auth/login` | POST | Login form submission |
| `/auth/validate` | GET | Every page load (layout) |
| `/filters/options` | GET | SearchBar mount |
| `/filters/create-token` | POST | Search submission |
| `/filters/verify-token` | POST | Search page load |
| `/search/media` | GET | After token verification |
| `/media/{uuid}` | GET | Media detail page load |
| `/ratings/media/{uuid}` | GET | Media detail page load (fetch user's rating) |
| `/ratings/media/{uuid}` | PUT | Create or update a rating |
| `/ratings/{uuid}` | DELETE | Delete a rating |

---

## 8. Error States

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
