/**
 * Per-tab session state for the navbar bell.
 *
 * sessionStorage persists across page navigations within the same tab — the
 * tab's lifetime, not the auth session's. Without explicit cleanup on logout,
 * a re-login in the same tab inherits the previous session's `bellLoginAt`
 * timestamp (so the bell still shows pre-logout jobs) and `bellSeenJobs` set
 * (so the badge stays cleared even though the user hasn't actually seen the
 * new session's jobs). The auth store subscribes to token changes and calls
 * clearBellSession() whenever the token transitions to null.
 */

export const BELL_LOGIN_KEY = 'phsar.bellLoginAt';
export const BELL_SEEN_KEY = 'phsar.bellSeenJobs';

export function clearBellSession(): void {
    if (typeof sessionStorage === 'undefined') return;
    sessionStorage.removeItem(BELL_LOGIN_KEY);
    sessionStorage.removeItem(BELL_SEEN_KEY);
}
