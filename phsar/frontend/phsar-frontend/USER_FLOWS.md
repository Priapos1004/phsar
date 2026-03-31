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

---

## 6. API Endpoints Used by Frontend

| Endpoint | Method | When |
|----------|--------|------|
| `/auth/login` | POST | Login form submission |
| `/auth/validate` | GET | Every page load (layout) |
| `/filters/options` | GET | SearchBar mount |
| `/filters/create-token` | POST | Search submission |
| `/filters/verify-token` | POST | Search page load |
| `/search/media` | GET | After token verification |

---

## 7. Error States

| Scenario | Expected Behavior |
|----------|-------------------|
| Login with wrong credentials | Red error message below form |
| Login network failure | "An unexpected error occurred." |
| Expired/invalid token on page load | Redirect to `/login` |
| Search API failure | Red error message on search page |
| Filter options fetch failure | Logged to console, search still works |
