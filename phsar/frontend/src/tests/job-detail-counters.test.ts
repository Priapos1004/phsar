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

describe('JobDetailCounters', () => {
	it('renders the v4 step1_failed value', () => {
		render(JobDetailCounters, { counters: makeCounters({ step1_failed: 49 }), version: 4 });
		const cell = screen.getByText('Failed refresh').parentElement;
		expect(cell?.textContent).toContain('49');
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
