import { describe, it, expect, beforeEach } from 'vitest';
import { get } from 'svelte/store';
import { token } from '$lib/stores/auth';

describe('auth store', () => {
	beforeEach(() => {
		localStorage.clear();
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
});
