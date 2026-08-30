import { describe, it, expect } from 'vitest';
import { byWindow } from '../lib/utils/jobHealth';
import type { AdminJobKindStats, JobKind } from '../lib/types/api';

const row = (kind: string, window_days: number): AdminJobKindStats => ({
	kind: kind as JobKind,
	window_days,
	succeeded: 0,
	failed: 0,
	retryable_failed: 0,
});

describe('byWindow', () => {
	it('un-interleaves the windows, which is how the API actually ships them', () => {
		// /admin/stats/overview emits one row per JobKind in enum order, so the
		// 7d and 90d kinds alternate. Feeding that exact order is the point of
		// this case — a grouping that only worked on pre-sorted input would
		// pass a tidier fixture and fail in production.
		const out = byWindow([
			row('user_scrape', 7),
			row('update_sweep', 7),
			row('seasonal_sweep', 90),
			row('upcoming_sweep', 90),
			row('backup', 7),
			row('restore', 90),
		]);
		expect(out.map((g) => g.days)).toEqual([7, 90]);
		// Backend order preserved inside each group: `backup` trails the other
		// two 7d kinds because that is where JobKind puts it.
		expect(out[0].rows.map((r) => r.kind)).toEqual(['user_scrape', 'update_sweep', 'backup']);
		expect(out[1].rows.map((r) => r.kind)).toEqual(['seasonal_sweep', 'upcoming_sweep', 'restore']);
	});

	it('orders groups shortest window first, whatever order the windows arrive in', () => {
		const out = byWindow([row('restore', 90), row('backup', 7), row('seasonal_sweep', 30)]);
		expect(out.map((g) => g.days)).toEqual([7, 30, 90]);
	});

	it('returns no groups for no rows', () => {
		expect(byWindow([])).toEqual([]);
	});
});
