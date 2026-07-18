import { describe, it, expect, vi, beforeEach, afterEach } from 'vitest';
import { get } from 'svelte/store';
import { activeToast, pushToast } from '../lib/stores/toast';

describe('toast store', () => {
	beforeEach(() => {
		activeToast.set(null);
		vi.useFakeTimers();
	});

	afterEach(() => {
		vi.useRealTimers();
		activeToast.set(null);
	});

	it('sets the active toast with the given variant', () => {
		pushToast('Saved', 'success');
		const t = get(activeToast);
		expect(t?.message).toBe('Saved');
		expect(t?.variant).toBe('success');
	});

	it('defaults to the info variant', () => {
		pushToast('Heads up');
		expect(get(activeToast)?.variant).toBe('info');
	});

	it('auto-clears after the duration', () => {
		pushToast('Bye', 'error', 1000);
		expect(get(activeToast)).not.toBeNull();
		vi.advanceTimersByTime(1000);
		expect(get(activeToast)).toBeNull();
	});

	it('a newer toast replaces the current one and resets the timer', () => {
		pushToast('First', 'info', 1000);
		vi.advanceTimersByTime(800);
		pushToast('Second', 'success', 1000);
		// The first toast's 1000ms window would have elapsed at 1000ms total,
		// but the second push reset the timer — at 1000ms total the second is
		// still showing.
		vi.advanceTimersByTime(200);
		const t = get(activeToast);
		expect(t?.message).toBe('Second');
		expect(t?.variant).toBe('success');
		// Its own full window then clears it.
		vi.advanceTimersByTime(800);
		expect(get(activeToast)).toBeNull();
	});

	it('gives each toast a distinct monotonic id', () => {
		pushToast('one');
		const first = get(activeToast)?.id;
		pushToast('two');
		const second = get(activeToast)?.id;
		expect(first).toBeDefined();
		expect(second).toBeDefined();
		expect(second).not.toBe(first);
	});
});
