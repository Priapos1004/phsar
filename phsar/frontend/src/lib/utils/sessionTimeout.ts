/**
 * Pure session-timeout decision logic — the testable heart of the sliding
 * session (SessionTimeoutBanner.svelte drives it on a 1s tick).
 *
 * The JWT `exp` claim is the single authoritative idle clock. While the user
 * is active the token is silently re-issued via POST /auth/refresh (so an
 * active session never lapses); an idle user is warned over the last few
 * minutes and then logged out. "Idle" is not a tracked state — it's simply
 * "no input within ACTIVITY_WINDOW_MS", so an idle user never enters the
 * refresh branch and the token decays into the warning + logout.
 */

// Warn when the token has <= this remaining. With a 10-min backend lifetime
// this surfaces the countdown banner after ~7 min of no interaction.
export const WARNING_LEAD_MS = 3 * 60_000;

// An active user refreshes once the token drops below this (~half-life on a
// 10-min token), comfortably before the warning would ever show. A successful
// refresh resets `remaining` to a full lifetime, so this threshold is also the
// rate limiter — refresh can't re-fire until the token decays back under it
// (no separate min-interval constant needed). MUST stay > WARNING_LEAD_MS.
export const REFRESH_THRESHOLD_MS = 5 * 60_000;

// Input within this window counts as "active". MUST stay below
// (lifetime - REFRESH_THRESHOLD_MS) so an active user always re-arms a refresh
// before the threshold lapses.
export const ACTIVITY_WINDOW_MS = 60_000;

// Tick cadence — drives both the refresh check and the m:ss countdown.
export const TICK_MS = 1000;

export type SessionAction = 'logout' | 'refresh' | 'warn' | 'idle';

export interface SessionInputs {
	/** JWT `exp` claim, in SECONDS (as jwt-decode returns it), or null/undefined when unknown. */
	exp: number | null | undefined;
	/** Current time in ms (Date.now()). */
	now: number;
	/** Timestamp (ms) of the last user interaction. */
	lastActivity: number;
}

export interface SessionDecision {
	action: SessionAction;
	remainingMs: number;
}

/**
 * Decide what the session machinery should do this tick. Pure — no clocks,
 * no DOM, no network — so every branch boundary is unit-testable.
 *
 * A missing/invalid `exp` is treated as 'logout' (remainingMs 0): the caller
 * already only runs this with a decoded token, so a falsy exp means a
 * malformed token that shouldn't keep a session alive.
 */
export function evaluateSession({ exp, now, lastActivity }: SessionInputs): SessionDecision {
	if (!exp || !Number.isFinite(exp)) {
		return { action: 'logout', remainingMs: 0 };
	}

	const remainingMs = exp * 1000 - now;
	const activeRecently = now - lastActivity < ACTIVITY_WINDOW_MS;

	if (remainingMs <= 0) {
		return { action: 'logout', remainingMs: 0 };
	}
	if (activeRecently && remainingMs < REFRESH_THRESHOLD_MS) {
		return { action: 'refresh', remainingMs };
	}
	if (remainingMs <= WARNING_LEAD_MS) {
		return { action: 'warn', remainingMs };
	}
	return { action: 'idle', remainingMs };
}

/** Format a remaining-ms value as an `m:ss` countdown (clamped at 0:00). */
export function formatCountdown(remainingMs: number): string {
	const totalSeconds = Math.max(0, Math.ceil(remainingMs / 1000));
	const minutes = Math.floor(totalSeconds / 60);
	const seconds = totalSeconds % 60;
	return `${minutes}:${seconds.toString().padStart(2, '0')}`;
}
