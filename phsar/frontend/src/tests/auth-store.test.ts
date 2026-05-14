import { describe, it, expect, beforeEach } from 'vitest';
import { get } from 'svelte/store';
import { token } from '$lib/stores/auth';
import { BELL_LOGIN_KEY, BELL_SEEN_KEY } from '$lib/stores/bell-session';

describe('auth store', () => {
	beforeEach(() => {
		localStorage.clear();
		sessionStorage.clear();
		token.set(null);
	});

	it('initializes as null when no localStorage value', () => {
		expect(get(token)).toBeNull();
	});

	it('persists token to localStorage on set', () => {
		token.set('test-jwt-token');
		expect(localStorage.getItem('token')).toBe('test-jwt-token');
	});

	it('clears localStorage when set to null', () => {
		token.set('test-jwt-token');
		token.set(null);
		expect(localStorage.getItem('token')).toBeNull();
	});

	it('clears bell session-scoped state when token is set to null', () => {
		// Simulate an existing bell session in the same tab — sessionStorage
		// would otherwise survive a logout-and-re-login cycle and keep the
		// previous session's timestamp + seen-uuids set, hiding new jobs.
		sessionStorage.setItem(BELL_LOGIN_KEY, '2026-05-09T08:00:00Z');
		sessionStorage.setItem(BELL_SEEN_KEY, '["aaa","bbb"]');

		token.set('test-jwt-token');
		token.set(null);

		expect(sessionStorage.getItem(BELL_LOGIN_KEY)).toBeNull();
		expect(sessionStorage.getItem(BELL_SEEN_KEY)).toBeNull();
	});
});
