import { describe, it, expect } from 'vitest';
import { get } from 'svelte/store';
import {
	sanitizeKind,
	sanitizePage,
	sanitizeStatus,
	jobsFilter,
	clearJobsFilter,
} from '$lib/stores/adminJobsFilter';

describe('sanitizeKind / sanitizeStatus', () => {
	it('passes through known values', () => {
		expect(sanitizeKind('update_sweep')).toBe('update_sweep');
		expect(sanitizeStatus('failed')).toBe('failed');
	});

	it('rejects unknown / null values to ""', () => {
		expect(sanitizeKind(null)).toBe('');
		expect(sanitizeKind('')).toBe('');
		expect(sanitizeKind('not_a_kind')).toBe('');
		expect(sanitizeStatus('pending')).toBe(''); // not a JobStatus
	});

	it('rejects injection-shaped values (whitelist, not interpolation)', () => {
		expect(sanitizeStatus("failed' OR 1=1")).toBe('');
		expect(sanitizeKind('update_sweep; DROP TABLE jobs')).toBe('');
		expect(sanitizeKind('<script>alert(1)</script>')).toBe('');
	});
});

describe('sanitizePage', () => {
	it('passes through a real page number', () => {
		expect(sanitizePage(1)).toBe(1);
		expect(sanitizePage(7)).toBe(7);
	});

	// Pages are 1-based, so 0 is as invalid as -1 — falling back to 0 would ask the
	// table for a page that does not exist.
	it('falls back to the first page for anything that is not one', () => {
		expect(sanitizePage(0)).toBe(1);
		expect(sanitizePage(-3)).toBe(1);
		expect(sanitizePage(2.5)).toBe(1);
		expect(sanitizePage('3')).toBe(1);
		expect(sanitizePage(null)).toBe(1);
		expect(sanitizePage(Number.NaN)).toBe(1);
		expect(sanitizePage(Number.POSITIVE_INFINITY)).toBe(1);
	});
});

describe('jobsFilter store + clearJobsFilter', () => {
	it('defaults to an empty filter on page 1', () => {
		clearJobsFilter();
		expect(get(jobsFilter)).toEqual({ kind: '', status: '', page: 1 });
	});

	it('clearJobsFilter resets a set filter, the page included', () => {
		jobsFilter.set({ kind: 'update_sweep', status: 'failed', page: 3 });
		clearJobsFilter();
		expect(get(jobsFilter)).toEqual({ kind: '', status: '', page: 1 });
	});

	// The envelope version gates rehydration: a stored v1 payload has no `page`, and
	// reading it back would land the admin on page 1 while believing otherwise.
	it('persists under the version that knows about the page', () => {
		jobsFilter.set({ kind: '', status: 'failed', page: 2 });
		expect(JSON.parse(sessionStorage.getItem('phsar.filter.adminJobs')!).v).toBe(2);
		clearJobsFilter();
	});
});
