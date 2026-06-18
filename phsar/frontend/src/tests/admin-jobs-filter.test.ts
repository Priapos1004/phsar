import { describe, it, expect } from 'vitest';
import { get } from 'svelte/store';
import {
	sanitizeKind,
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

describe('jobsFilter store + clearJobsFilter', () => {
	it('defaults to an empty filter', () => {
		clearJobsFilter();
		expect(get(jobsFilter)).toEqual({ kind: '', status: '' });
	});

	it('clearJobsFilter resets a set filter back to empty', () => {
		jobsFilter.set({ kind: 'update_sweep', status: 'failed' });
		expect(get(jobsFilter)).toEqual({ kind: 'update_sweep', status: 'failed' });
		clearJobsFilter();
		expect(get(jobsFilter)).toEqual({ kind: '', status: '' });
	});
});
