import { describe, it, expect, vi, beforeEach } from 'vitest';
import { render, screen, fireEvent, waitFor } from '@testing-library/svelte';
import CompletionStatusCard from '$lib/components/admin/CompletionStatusCard.svelte';
import { api } from '$lib/api';
import { fetchAnimeSearchResults } from '$lib/utils/search';
import type { FinishedAnimeItem } from '$lib/types/api';

vi.mock('$lib/api', () => ({
	api: { get: vi.fn(), post: vi.fn(), del: vi.fn() },
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

vi.mock('$lib/utils/search', () => ({ fetchAnimeSearchResults: vi.fn() }));

const ANIME_UUID = 'aaaaaaaa-aaaa-aaaa-aaaa-aaaaaaaaaaaa';

function summary(): FinishedAnimeItem {
	return {
		uuid: ANIME_UUID,
		title: 'Finished Anime',
		name_eng: null,
		name_jap: null,
		cover_image: null,
		marked_by_username: 'admin',
		marked_at: '2026-06-21T10:00:00Z',
	};
}

describe('CompletionStatusCard', () => {
	beforeEach(() => {
		vi.mocked(api.get).mockResolvedValue([summary()]);
		vi.mocked(api.post).mockResolvedValue(undefined);
		vi.mocked(api.del).mockResolvedValue(undefined);
		vi.mocked(fetchAnimeSearchResults).mockResolvedValue([]);
	});

	it('lists currently-marked anime on mount', async () => {
		render(CompletionStatusCard);
		await waitFor(() => expect(screen.getByText('Finished Anime')).toBeInTheDocument());
		expect(api.get).toHaveBeenCalledWith('/admin/finished-anime');
	});

	it('arms on first click without deleting, then unmarks on confirm', async () => {
		render(CompletionStatusCard);
		await waitFor(() => expect(screen.getByText('Finished Anime')).toBeInTheDocument());

		// First click only arms the guard — no DELETE yet.
		await fireEvent.click(screen.getByLabelText('Remove story-complete flag'));
		expect(api.del).not.toHaveBeenCalled();

		// The armed button now asks for confirmation; the second click removes.
		await fireEvent.click(screen.getByLabelText('Confirm removal of story-complete flag'));
		expect(api.del).toHaveBeenCalledWith(`/admin/finished-anime/${ANIME_UUID}`);
	});
});
