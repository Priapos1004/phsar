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
	it('renders v4 anime-grained headline + rollups', () => {
		render(JobDetailCounters, { counters: makeCounters({ anime_refreshed: 64 }), version: 4 });
		const cell = screen.getByText('Anime touched').parentElement;
		expect(cell?.textContent).toContain('64');
		// v4 still shows the per-anime rollups.
		expect(screen.queryByText('Anime w/ dynamic')).not.toBeNull();
		// v5-only counters are absent.
		expect(screen.queryByText('Media refreshed')).toBeNull();
		expect(screen.queryByText('Media skipped')).toBeNull();
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

	it('does not render the failure counts in the grid (the cards below carry them)', () => {
		// step1_failed / probe_failed are intentionally absent from the grid —
		// the amber "Failed refresh" / "Failed probe" cards own that signal.
		render(JobDetailCounters, {
			counters: makeV5Counters({ step1_failed: 3, probe_failed: 2 }),
			version: 6,
		});
		expect(screen.queryByText('Failed refresh')).toBeNull();
		expect(screen.queryByText('Probes failed')).toBeNull();
	});

	it('uses the softened "Anime changed" / "Anime w/ new media" labels', () => {
		render(JobDetailCounters, {
			counters: makeV5Counters({ umbrella_reclassed: 4, probe_attached_anime_count: 2 }),
			version: 6,
		});
		expect(screen.getByText('Anime changed').parentElement?.textContent).toContain('4');
		expect(screen.getByText('Anime w/ new media').parentElement?.textContent).toContain('2');
		expect(screen.queryByText('Anime reclassed')).toBeNull();
		expect(screen.queryByText('Anime w/ new attach')).toBeNull();
	});
});
