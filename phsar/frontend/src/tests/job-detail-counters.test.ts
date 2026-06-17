import { describe, it, expect } from 'vitest';
import { render, screen } from '@testing-library/svelte';
import JobDetailCounters from '../lib/components/admin/JobDetailCounters.svelte';
import type { UpdateSweepCounters } from '../lib/types/api';

function makeCounters(overrides: Partial<UpdateSweepCounters> = {}): UpdateSweepCounters {
	return {
		anime_refreshed: 64,
		anime_with_dynamic_changes: 51,
		anime_with_static_changes: 0,
		media_with_dynamic_changes: 56,
		media_with_static_changes: 0,
		umbrella_reclassed: 0,
		probe_succeeded: 0,
		probe_failed: 0,
		probe_attached_anime_count: 0,
		orphaned_studios_removed: 15,
		...overrides,
	};
}

function makeV5Counters(overrides: Partial<UpdateSweepCounters> = {}): UpdateSweepCounters {
	return {
		media_refreshed: 120,
		anime_touched: 40,
		media_skipped_fresh: 200,
		media_with_dynamic_changes: 56,
		media_with_static_changes: 0,
		umbrella_reclassed: 0,
		probe_succeeded: 0,
		probe_failed: 0,
		probe_attached_anime_count: 0,
		orphaned_studios_removed: 15,
		...overrides,
	};
}

describe('JobDetailCounters', () => {
	it('renders the v4 step1_failed value', () => {
		render(JobDetailCounters, { counters: makeCounters({ step1_failed: 49 }), version: 4 });
		const cell = screen.getByText('Failed refresh').parentElement;
		expect(cell?.textContent).toContain('49');
	});

	it('renders v4 anime-grained headline + rollups', () => {
		render(JobDetailCounters, { counters: makeCounters({ anime_refreshed: 64 }), version: 4 });
		const cell = screen.getByText('Anime touched').parentElement;
		expect(cell?.textContent).toContain('64');
		// v4 still shows the per-anime rollups.
		expect(screen.queryByText('Anime w/ dynamic')).not.toBeNull();
		// v5-only counters are absent.
		expect(screen.queryByText('Media refreshed')).toBeNull();
		expect(screen.queryByText('Media skipped (fresh)')).toBeNull();
	});

	it('renders v5 media-grained counters and drops the anime rollups', () => {
		render(JobDetailCounters, { counters: makeV5Counters(), version: 5 });
		expect(screen.getByText('Media refreshed').parentElement?.textContent).toContain('120');
		expect(screen.getByText('Anime touched').parentElement?.textContent).toContain('40');
		expect(screen.getByText('Media skipped').parentElement?.textContent).toContain('200');
		// The v2–v4 per-anime rollups are gone in v5.
		expect(screen.queryByText('Anime w/ dynamic')).toBeNull();
		expect(screen.queryByText('Anime w/ static')).toBeNull();
	});

	it('still renders the step1_failed cell on v5 (kept across the bump)', () => {
		render(JobDetailCounters, { counters: makeV5Counters({ step1_failed: 3 }), version: 5 });
		const cell = screen.getByText('Failed refresh').parentElement;
		expect(cell?.textContent).toContain('3');
		expect(cell?.className).toContain('amber');
	});

	it('renders "—" for the step1_failed cell on pre-v4 rows (not a misleading 0)', () => {
		// v3 rows never tracked step1_failed; counters omits the key.
		render(JobDetailCounters, { counters: makeCounters(), version: 3 });
		const cell = screen.getByText('Failed refresh').parentElement;
		expect(cell?.textContent).toContain('—');
		expect(cell?.textContent).not.toContain('0');
	});

	it('tints the step1_failed cell amber when failures occurred', () => {
		render(JobDetailCounters, { counters: makeCounters({ step1_failed: 49 }), version: 4 });
		const cell = screen.getByText('Failed refresh').parentElement;
		expect(cell?.className).toContain('amber');
	});

	it('does not tint when step1_failed is zero on v4', () => {
		render(JobDetailCounters, { counters: makeCounters({ step1_failed: 0 }), version: 4 });
		const cell = screen.getByText('Failed refresh').parentElement;
		expect(cell?.className).not.toContain('amber');
	});
});
