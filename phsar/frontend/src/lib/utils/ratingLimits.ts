/** Limits the rating form enforces on input, each mirroring a server-side clamp. */

/**
 * Upper bound for `episodes_watched` when the catalogue has no episode total —
 * a still-airing long-runner (One Piece is ~1100) stays well under it.
 *
 * Must equal `UNKNOWN_EPISODES_CAP` in `app/services/rating_service.py`. Walked
 * by `tests/routers/test_ratings.py::test_unknown_episodes_cap_matches_the_client`,
 * which reads this file from the backend suite, and by
 * `rating-modal.test.ts` for the half that check cannot see — that the form
 * still uses it.
 */
export const UNKNOWN_EPISODES_CAP = 2000;
