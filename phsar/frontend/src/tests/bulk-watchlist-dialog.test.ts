import { describe, it, expect, vi, beforeEach } from 'vitest';
import { render, screen, fireEvent, waitFor } from '@testing-library/svelte';
import { get } from 'svelte/store';
import BulkWatchlistDialog from '$lib/components/BulkWatchlistDialog.svelte';
import { api } from '$lib/api';
import { tags } from '$lib/stores/tags';
import type { WatchlistOut } from '$lib/types/api';

vi.mock('$lib/api', () => ({
	api: { get: vi.fn(), put: vi.fn(), post: vi.fn(), del: vi.fn() },
	ApiError: class extends Error {
		status: number;
		detail: string;
		constructor(status: number, detail: string) {
			super(detail);
			this.status = status;
			this.detail = detail;
		}
	},
}));

vi.mock('$lib/stores/watchlist', () => ({
	refreshWatchlist: vi.fn().mockResolvedValue(undefined),
	watchlistTags: { subscribe: (fn: (v: Map<string, unknown>) => void) => (fn(new Map()), () => {}) },
}));

vi.mock('$lib/stores/toast', () => ({ pushToast: vi.fn() }));

const ANIME = 'aaaaaaaa-aaaa-aaaa-aaaa-aaaaaaaaaaaa';
const M1 = 'm1111111-1111-1111-1111-111111111111';
const M2 = 'm2222222-2222-2222-2222-222222222222';
const TAG = 'tag00000-0000-0000-0000-000000000000';

function entry(mediaUuid: string, priority: number, note: string | null): WatchlistOut {
	return {
		uuid: `e-${mediaUuid}`,
		priority,
		note,
		tag: { uuid: TAG, name: 'Watchlist', color: '#f80' },
		media_uuid: mediaUuid,
		media_title: 'M',
		media_cover_image: null,
		anime_uuid: ANIME,
		anime_title: 'A',
		created_at: '2026-01-01T00:00:00Z',
		modified_at: '2026-01-01T00:00:00Z',
	} as WatchlistOut;
}

/** The GET /watchlist/anime/{uuid} payload: rows plus the server-named note target. */
function payload(entries: WatchlistOut[], noteTarget: string | null = entries[0]?.media_uuid ?? null) {
	return { entries, note_target_media_uuid: noteTarget };
}

/** The body of the one PUT /watchlist/bulk the dialog sent. */
function bulkBody(): Record<string, unknown> {
	const call = vi.mocked(api.put).mock.calls.find((c) => c[0] === '/watchlist/bulk');
	expect(call, 'expected a PUT /watchlist/bulk').toBeTruthy();
	return call![1] as Record<string, unknown>;
}

describe('BulkWatchlistDialog — update mode', () => {
	beforeEach(() => {
		vi.mocked(api.put).mockReset();
		vi.mocked(api.get).mockReset();
		vi.mocked(api.put).mockResolvedValue([]);
		tags.set([{
			uuid: TAG, name: 'Watchlist', color: '#f80', is_default: true,
			entry_count: 2, anime_count: 1,
			created_at: '2026-01-01T00:00:00Z', modified_at: '2026-01-01T00:00:00Z',
		}]);
	});

	it('prefills the stored priority instead of resetting it, and keeps it on a list change', async () => {
		// The reported bug: an entry added at High came back Medium/Low after a list swap,
		// because the dialog opened on its default rather than on what was stored.
		vi.mocked(api.get).mockResolvedValue(payload([entry(M1, 1, null), entry(M2, 1, null)]));
		render(BulkWatchlistDialog, { props: { open: true, mediaUuids: [M1, M2], animeUuid: ANIME } });

		await waitFor(() => expect(screen.getByText('Update watchlist entry')).toBeTruthy());
		// High is the selected pill — the picker marks the active one with the primary text token.
		const high = screen.getByRole('button', { name: 'High' });
		expect(high.className).toContain('text-primary');

		await fireEvent.click(screen.getByRole('button', { name: /^Update/ }));
		await waitFor(() => expect(vi.mocked(api.put)).toHaveBeenCalled());
		expect(bulkBody().priority).toBe(1);
	});

	it('omits the note when the field was not edited, so a priority change keeps every note', async () => {
		// Two media each carrying their own note. The client cannot know which one the
		// backend writes to, so an untouched field must not be sent at all — sending it
		// rewrites one entry's note onto another and destroys the second.
		vi.mocked(api.get).mockResolvedValue(payload([entry(M1, 3, 'note A'), entry(M2, 3, 'note B')]));
		render(BulkWatchlistDialog, { props: { open: true, mediaUuids: [M1, M2], animeUuid: ANIME } });

		await waitFor(() => expect(screen.getByText('Update watchlist entry')).toBeTruthy());
		await fireEvent.click(screen.getByRole('button', { name: 'High' }));
		await fireEvent.click(screen.getByRole('button', { name: /^Update/ }));

		await waitFor(() => expect(vi.mocked(api.put)).toHaveBeenCalled());
		const body = bulkBody();
		expect(body.priority).toBe(1);
		expect('note' in body).toBe(false);
	});

	it('does not send a note the user never typed in, even when one is shown', async () => {
		// The strongest form of the guard: the box is prefilled, the user only touches
		// priority, and the request must still carry no note at all.
		vi.mocked(api.get).mockResolvedValue(payload([entry(M1, 3, 'note A'), entry(M2, 3, 'note B')]));
		render(BulkWatchlistDialog, { props: { open: true, mediaUuids: [M1, M2], animeUuid: ANIME } });

		await waitFor(() => expect(screen.getByText('Update watchlist entry')).toBeTruthy());
		expect((screen.getByPlaceholderText('Optional note…') as HTMLTextAreaElement).value).toBeTruthy();
		await fireEvent.click(screen.getByRole('button', { name: 'High' }));
		await fireEvent.click(screen.getByRole('button', { name: /^Update/ }));

		await waitFor(() => expect(vi.mocked(api.put)).toHaveBeenCalled());
		expect('note' in bulkBody()).toBe(false);
	});

	it('sends the note once it is edited', async () => {
		vi.mocked(api.get).mockResolvedValue(payload([entry(M1, 3, 'note A')]));
		render(BulkWatchlistDialog, { props: { open: true, mediaUuids: [M1], animeUuid: ANIME } });

		await waitFor(() => expect(screen.getByText('Update watchlist entry')).toBeTruthy());
		const box = screen.getByPlaceholderText('Optional note…');
		expect((box as HTMLTextAreaElement).value).toBe('note A'); // prefilled from the stored note
		await fireEvent.input(box, { target: { value: 'note A revised' } });
		await fireEvent.click(screen.getByRole('button', { name: /^Update/ }));

		await waitFor(() => expect(vi.mocked(api.put)).toHaveBeenCalled());
		expect(bulkBody().note).toBe('note A revised');
	});

	it('shows the note of the media the backend writes to, not just any noted entry', async () => {
		// The row order of GET /watchlist/anime is not the client's business, so the
		// server names the target. Here the SECOND row is it: prefilling from the first
		// noted row would show one note and then overwrite a different media's.
		vi.mocked(api.get).mockResolvedValue(
			payload([entry(M1, 3, 'note A'), entry(M2, 3, 'note B')], M2)
		);
		render(BulkWatchlistDialog, { props: { open: true, mediaUuids: [M1, M2], animeUuid: ANIME } });

		await waitFor(() => expect(screen.getByText('Update watchlist entry')).toBeTruthy());
		expect((screen.getByPlaceholderText('Optional note…') as HTMLTextAreaElement).value).toBe('note B');
		expect(screen.getByText(/1 other media keeps its own note/)).toBeTruthy();
	});

	it('preselects nothing when the entries disagree, so no value is silently applied', async () => {
		vi.mocked(api.get).mockResolvedValue(payload([entry(M1, 1, null), entry(M2, 3, null)]));
		render(BulkWatchlistDialog, { props: { open: true, mediaUuids: [M1, M2], animeUuid: ANIME } });

		await waitFor(() => expect(screen.getByText(/span/)).toBeTruthy());
		for (const label of ['High', 'Medium', 'Low']) {
			expect(screen.getByRole('button', { name: label }).className).not.toContain('text-primary');
		}
		expect(screen.getByRole('button', { name: /^Update/ }).hasAttribute('disabled')).toBe(true);
	});

	it('adds on defaults when nothing is listed yet', async () => {
		vi.mocked(api.get).mockResolvedValue(payload([]));
		render(BulkWatchlistDialog, { props: { open: true, mediaUuids: [M1], animeUuid: ANIME } });

		await waitFor(() => expect(screen.getByText('Add to watchlist')).toBeTruthy());
		await fireEvent.click(screen.getByRole('button', { name: /^Add 1/ }));
		await waitFor(() => expect(vi.mocked(api.put)).toHaveBeenCalled());
		expect(bulkBody().priority).toBe(3);
		expect(get(tags)[0].uuid).toBe(bulkBody().tag_uuid); // the default list
	});
});
