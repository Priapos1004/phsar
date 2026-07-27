import { describe, it, expect } from 'vitest';
import {
	payloadSummary,
	unknownGenreTags,
	probeAttachedMedia,
	hentaiRemoved,
	rowTintClass,
} from '$lib/utils/jobSummary';
import type { AdminJobResponse, JobKind, JobResultSummary, JobStatus } from '$lib/types/api';

function row(over: {
	kind: JobKind;
	version?: number;
	status?: JobStatus;
	payload?: Record<string, unknown>;
	result_summary?: JobResultSummary | null;
}): AdminJobResponse {
	return {
		uuid: 'u1',
		kind: over.kind,
		version: over.version ?? 1,
		status: over.status ?? 'succeeded',
		payload: over.payload ?? {},
		stage: null,
		items_total: null,
		items_done: 0,
		result_summary: over.result_summary ?? null,
		error_message: null,
		created_at: '2026-07-27T00:00:00Z',
		started_at: null,
		finished_at: null,
		requested_by_username: null,
		parent_job_uuid: null,
	};
}

describe('payloadSummary — season sweeps', () => {
	// Both kinds run the same dispatcher and write the same summary, so an
	// upcoming_sweep must render exactly what a seasonal_sweep does. It didn't
	// before v0.15.3 (the branch was gated on the seasonal_sweep literal).
	const summary = {
		season_year: 2026,
		season_name: 'Fall',
		season_entries: 69,
		new_entries_enqueued: 64,
		dedup_skipped: 5,
	};

	it('renders identically for seasonal_sweep and upcoming_sweep', () => {
		const expected =
			'Fall 2026 · 69 season entries · 64 new scrapes enqueued · 5 already known';
		expect(payloadSummary(row({ kind: 'seasonal_sweep', result_summary: summary }))).toBe(expected);
		expect(payloadSummary(row({ kind: 'upcoming_sweep', result_summary: summary }))).toBe(expected);
	});

	it('drops the season prefix on a pre-v0.15.3 row that lacks the additive keys', () => {
		const legacy = { season_entries: 163, new_entries_enqueued: 2, dedup_skipped: 161 };
		expect(payloadSummary(row({ kind: 'upcoming_sweep', result_summary: legacy }))).toBe(
			'163 season entries · 2 new scrapes enqueued · 161 already known',
		);
	});

	it('drops the prefix when only half the season pair is present', () => {
		const half = { season_name: 'Fall', season_entries: 1, new_entries_enqueued: 1, dedup_skipped: 0 };
		expect(payloadSummary(row({ kind: 'seasonal_sweep', result_summary: half }))).toBe(
			'1 season entries · 1 new scrapes enqueued · 0 already known',
		);
	});

	it('is empty for a failed sweep', () => {
		expect(
			payloadSummary(row({ kind: 'upcoming_sweep', status: 'failed', result_summary: summary })),
		).toBe('');
	});
});

describe('payloadSummary — backup / restore', () => {
	it('appends the dump size to a backup', () => {
		const s = { filename: 'phsar-20260628-143406-manual.dump', size_bytes: 7431529 };
		expect(payloadSummary(row({ kind: 'backup', result_summary: s }))).toBe(
			'phsar-20260628-143406-manual.dump · 7.1 MB',
		);
	});

	it('shows the filename alone when no size is recorded (restore, or a legacy row)', () => {
		const s = {
			restored_from: 'phsar-20260616-122017-manual.dump',
			filename: 'phsar-20260616-122017-manual.dump',
		};
		expect(payloadSummary(row({ kind: 'restore', result_summary: s }))).toBe(
			'phsar-20260616-122017-manual.dump',
		);
	});

	it('is empty when the summary carries no filename', () => {
		expect(payloadSummary(row({ kind: 'backup', result_summary: {} }))).toBe('');
		expect(payloadSummary(row({ kind: 'backup', result_summary: null }))).toBe('');
	});
});

describe('payloadSummary — user_scrape', () => {
	it('shows the counts with the query', () => {
		expect(
			payloadSummary(
				row({
					kind: 'user_scrape',
					payload: { query: 'Zenshu' },
					result_summary: { anime_count: 1, media_count: 3 },
				}),
			),
		).toBe('+1 anime · +3 media ("Zenshu")');
	});

	it('falls back to the bare query while queued', () => {
		expect(
			payloadSummary(row({ kind: 'user_scrape', status: 'queued', payload: { query: 'Zenshu' } })),
		).toBe('"Zenshu"');
	});
});

describe('payloadSummary — update_sweep version eras', () => {
	const sweep = (version: number, result_summary: JobResultSummary) =>
		payloadSummary(row({ kind: 'update_sweep', version, result_summary }));

	it('v5+ reads the media-grained counters', () => {
		expect(
			sweep(7, {
				counters: { media_refreshed: 42, media_with_dynamic_changes: 8, media_with_static_changes: 2 },
			}),
		).toBe('42 media refreshed · 8 media w/ dynamic · 2 media w/ static');
	});

	it('v2–v4 keeps the anime-grained keys', () => {
		expect(sweep(4, { counters: { anime_refreshed: 10, anime_with_dynamic_changes: 3 } })).toBe(
			'10 touched · 3 anime w/ dynamic',
		);
	});

	it('v1 falls back to the flat pre-rework shape', () => {
		expect(sweep(1, { anime_refreshed: 5, anime_changed: 2, metadata_changed_media: 1 })).toBe(
			'refreshed 5 anime · 2 changed · 1 media updated',
		);
	});

	it('omits zero-valued optional segments', () => {
		expect(sweep(7, { counters: { media_refreshed: 3 } })).toBe('3 media refreshed');
	});
});

describe('row-level signals', () => {
	it('unknownGenreTags tolerates a missing or malformed list', () => {
		expect(unknownGenreTags(row({ kind: 'update_sweep', result_summary: { unknown_genre_tags: ['Ecchi'] } }))).toEqual(['Ecchi']);
		expect(unknownGenreTags(row({ kind: 'update_sweep', result_summary: {} }))).toEqual([]);
		expect(unknownGenreTags(row({ kind: 'update_sweep', result_summary: { unknown_genre_tags: 'Ecchi' } }))).toEqual([]);
	});

	it('probeAttachedMedia / hentaiRemoved default to 0 on older versions', () => {
		const r = row({ kind: 'update_sweep', version: 5, result_summary: { counters: {} } });
		expect(probeAttachedMedia(r)).toBe(0);
		expect(hentaiRemoved(r)).toBe(0);
		const v7 = row({
			kind: 'update_sweep',
			version: 7,
			result_summary: { counters: { probe_attached_media_count: 4, hentai_removed_count: 1 } },
		});
		expect(probeAttachedMedia(v7)).toBe(4);
		expect(hentaiRemoved(v7)).toBe(1);
	});

	it('rowTintClass is single-winner: hentai > unknown tags > probe', () => {
		expect(rowTintClass(1, 5, 3)).toContain('rose');
		expect(rowTintClass(0, 5, 3)).toContain('amber');
		expect(rowTintClass(0, 0, 3)).toContain('blue');
		expect(rowTintClass(0, 0, 0)).toBe('');
	});
});
