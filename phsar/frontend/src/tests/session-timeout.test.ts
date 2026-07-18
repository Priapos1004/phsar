import { describe, it, expect, vi, beforeEach, afterEach } from 'vitest';
import { flushSync } from 'svelte';
import { render, screen } from '@testing-library/svelte';
import {
	evaluateSession,
	formatCountdown,
	WARNING_LEAD_MS,
	REFRESH_THRESHOLD_MS,
	ACTIVITY_WINDOW_MS,
} from '../lib/utils/sessionTimeout';

// ---------------------------------------------------------------------------
// Pure decision logic — exhaustive boundaries, no DOM / clocks / network.
// ---------------------------------------------------------------------------
describe('evaluateSession', () => {
	const NOW = 1_700_000_000_000;
	// exp is in SECONDS; build one that is `ms` from NOW.
	const expIn = (ms: number) => Math.floor((NOW + ms) / 1000);
	const active = NOW; // last activity = now → fully active
	const idle = NOW - (ACTIVITY_WINDOW_MS + 1000); // beyond the activity window

	it('logs out when the token has expired', () => {
		expect(evaluateSession({ exp: expIn(-1000), now: NOW, lastActivity: active }).action).toBe(
			'logout',
		);
	});

	it('logs out at exactly remaining 0', () => {
		expect(evaluateSession({ exp: Math.floor(NOW / 1000), now: NOW, lastActivity: active }).action).toBe(
			'logout',
		);
	});

	it('logs out when exp is missing / non-finite', () => {
		expect(evaluateSession({ exp: null, now: NOW, lastActivity: active }).action).toBe('logout');
		expect(evaluateSession({ exp: undefined, now: NOW, lastActivity: active }).action).toBe('logout');
		expect(evaluateSession({ exp: NaN, now: NOW, lastActivity: active }).action).toBe('logout');
	});

	it('refreshes when active and below the refresh threshold', () => {
		expect(
			evaluateSession({ exp: expIn(REFRESH_THRESHOLD_MS - 1000), now: NOW, lastActivity: active })
				.action,
		).toBe('refresh');
	});

	it('does NOT refresh when active but still above the threshold', () => {
		expect(
			evaluateSession({ exp: expIn(REFRESH_THRESHOLD_MS + 1000), now: NOW, lastActivity: active })
				.action,
		).toBe('idle');
	});

	it('active user gets refresh (not warn) even inside the warning window — never sees the banner', () => {
		expect(
			evaluateSession({ exp: expIn(WARNING_LEAD_MS - 1000), now: NOW, lastActivity: active }).action,
		).toBe('refresh');
	});

	it('idle user warns inside the warning window', () => {
		expect(
			evaluateSession({ exp: expIn(WARNING_LEAD_MS - 1000), now: NOW, lastActivity: idle }).action,
		).toBe('warn');
	});

	it('warns at exactly the warning-lead boundary (<=) when idle', () => {
		expect(
			evaluateSession({ exp: expIn(WARNING_LEAD_MS), now: NOW, lastActivity: idle }).action,
		).toBe('warn');
	});

	it('idle user between warning and threshold is idle (no refresh, no banner)', () => {
		// Idle so refresh is off the table; above the warning lead so no banner.
		expect(
			evaluateSession({ exp: expIn(WARNING_LEAD_MS + 1000), now: NOW, lastActivity: idle }).action,
		).toBe('idle');
	});

	it('reports remainingMs for non-terminal actions', () => {
		const d = evaluateSession({ exp: expIn(WARNING_LEAD_MS - 1000), now: NOW, lastActivity: idle });
		expect(d.remainingMs).toBeGreaterThan(0);
		expect(d.remainingMs).toBeLessThanOrEqual(WARNING_LEAD_MS);
	});
});

describe('formatCountdown', () => {
	it('formats minutes and zero-padded seconds', () => {
		expect(formatCountdown(180_000)).toBe('3:00');
		expect(formatCountdown(150_000)).toBe('2:30');
		expect(formatCountdown(59_000)).toBe('0:59');
		expect(formatCountdown(5_000)).toBe('0:05');
	});

	it('clamps at 0:00 for zero / negative', () => {
		expect(formatCountdown(0)).toBe('0:00');
		expect(formatCountdown(-5_000)).toBe('0:00');
	});

	it('rounds up partial seconds (ceil)', () => {
		expect(formatCountdown(1)).toBe('0:01');
		expect(formatCountdown(59_001)).toBe('1:00');
	});
});

// ---------------------------------------------------------------------------
// Component wiring — fake timers + mocked token store, api, and jwt-decode.
// ---------------------------------------------------------------------------
const { apiPost } = vi.hoisted(() => ({ apiPost: vi.fn() }));

vi.mock('jwt-decode', () => ({
	// Test "tokens" are JSON strings carrying the exp claim.
	jwtDecode: (t: string) => JSON.parse(t),
}));

vi.mock('$lib/stores/auth', async () => {
	const { writable } = await import('svelte/store');
	return { token: writable<string | null>(null) };
});

vi.mock('$lib/api', () => {
	class ApiError extends Error {
		status: number;
		detail: string;
		constructor(status: number, detail: string) {
			super(detail);
			this.status = status;
			this.detail = detail;
		}
	}
	return { api: { post: apiPost }, ApiError };
});

import SessionTimeoutBanner from '../lib/components/SessionTimeoutBanner.svelte';

const START = 1_700_000_000_000;
// Full token lifetime — matches the backend ACCESS_TOKEN_EXPIRE_MINUTES=10.
// Starting at full life keeps the user's initial (active) window ABOVE the
// refresh threshold, so the only refresh is the one we deliberately trigger.
const LIFETIME_MS = 10 * 60_000;
// Advance enough that the user is long idle AND the token has decayed into the
// warning window (without the active opening window ever entering refresh).
const TO_WARN_MS = LIFETIME_MS - WARNING_LEAD_MS + 2_000;
// A token string whose exp is `ms` from the (faked) current time.
const tokenRemaining = (ms: number) => JSON.stringify({ exp: Math.floor((Date.now() + ms) / 1000) });

describe('SessionTimeoutBanner', () => {
	beforeEach(async () => {
		vi.useFakeTimers();
		vi.setSystemTime(START);
		apiPost.mockReset();
		const { token } = await import('$lib/stores/auth');
		token.set(null);
	});

	afterEach(() => {
		vi.useRealTimers();
	});

	async function setToken(value: string | null) {
		const { token } = await import('$lib/stores/auth');
		token.set(value);
	}

	it('shows the countdown banner once an idle user enters the warning window', async () => {
		await setToken(tokenRemaining(LIFETIME_MS));
		render(SessionTimeoutBanner, { props: { onExpire: vi.fn() } });

		// Advance past the warning lead with no activity → idle → warn.
		await vi.advanceTimersByTimeAsync(TO_WARN_MS);
		flushSync();

		expect(screen.getByText(/signed out in/i)).toBeInTheDocument();
		// An idle user never enters the refresh branch — no silent refresh.
		expect(apiPost).not.toHaveBeenCalled();
	});

	it('refreshes once on activity and clears the warning (no logout)', async () => {
		const onExpire = vi.fn();
		await setToken(tokenRemaining(LIFETIME_MS));
		// A successful refresh hands back a fresh full-life token.
		apiPost.mockImplementation(async () => ({ access_token: tokenRemaining(LIFETIME_MS) }));
		render(SessionTimeoutBanner, { props: { onExpire } });

		// Drift into the warning window while idle.
		await vi.advanceTimersByTimeAsync(TO_WARN_MS);
		flushSync();
		expect(screen.getByText(/signed out in/i)).toBeInTheDocument();

		// User comes back → activity → next tick refreshes.
		window.dispatchEvent(new Event('mousedown'));
		await vi.advanceTimersByTimeAsync(1_500);
		flushSync();

		expect(apiPost).toHaveBeenCalledTimes(1);
		expect(apiPost).toHaveBeenCalledWith('/auth/refresh');
		expect(onExpire).not.toHaveBeenCalled();
		expect(screen.queryByText(/signed out in/i)).not.toBeInTheDocument();
	});

	it('fires onExpire exactly once when the token lapses while idle', async () => {
		const onExpire = vi.fn();
		await setToken(tokenRemaining(LIFETIME_MS));
		render(SessionTimeoutBanner, { props: { onExpire } });

		// Run well past expiry with no activity.
		await vi.advanceTimersByTimeAsync(LIFETIME_MS + 5_000);
		flushSync();

		expect(onExpire).toHaveBeenCalledTimes(1);
	});

	it('treats a 401 from refresh as terminal (onExpire)', async () => {
		const onExpire = vi.fn();
		const { ApiError } = await import('$lib/api');
		await setToken(tokenRemaining(LIFETIME_MS));
		apiPost.mockRejectedValue(new ApiError(401, 'expired'));
		render(SessionTimeoutBanner, { props: { onExpire } });

		// Idle into the warning window, then activity to fire the refresh.
		await vi.advanceTimersByTimeAsync(TO_WARN_MS);
		window.dispatchEvent(new Event('mousedown'));
		await vi.advanceTimersByTimeAsync(1_500);
		flushSync();

		expect(onExpire).toHaveBeenCalledTimes(1);
	});

	it('does not start a second refresh while one is in flight', async () => {
		await setToken(tokenRemaining(LIFETIME_MS));
		// A deferred (not a never-resolving promise) so we can settle it before
		// teardown and not leak a dangling await across test files.
		let settle: (v: { access_token: string }) => void = () => {};
		apiPost.mockImplementation(() => new Promise((resolve) => (settle = resolve)));
		render(SessionTimeoutBanner, { props: { onExpire: vi.fn() } });

		await vi.advanceTimersByTimeAsync(TO_WARN_MS);
		window.dispatchEvent(new Event('mousedown'));
		// Several ticks while the refresh hangs — the guard must hold.
		await vi.advanceTimersByTimeAsync(5_000);
		flushSync();

		expect(apiPost).toHaveBeenCalledTimes(1);

		// Settle the in-flight refresh so nothing dangles past the test.
		settle({ access_token: tokenRemaining(LIFETIME_MS) });
		await vi.advanceTimersByTimeAsync(0);
	});
});
