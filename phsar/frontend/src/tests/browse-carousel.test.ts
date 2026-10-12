import { describe, it, expect, vi, afterEach } from 'vitest';
import { render, screen, waitFor } from '@testing-library/svelte';
import BrowseCarousel from '$lib/components/BrowseCarousel.svelte';
import { api } from '$lib/api';
import { clearBrowseRows, clearSectionRows } from '$lib/stores/browseRows';
import type { AnimeSearchResult, BrowseCarousel as Carousel } from '$lib/types/api';

const continuations: Carousel = {
	key: 'announced-continuations',
	title: 'Announced continuations',
	params: { upcoming_main: true, rated: ['in_progress', 'on_hold'], sort: 'release' },
	see_all_limit: 1000,
	sortable: false,
	filter_sets: [],
	page: 'news',
};

// The row cache outlives a test, so a later test of the same row would read it, not fetch.
afterEach(() => {
	vi.restoreAllMocks();
	clearBrowseRows();
});

describe('BrowseCarousel', () => {
	it('tells a guest why a row over their own ratings is empty, and searches nothing', () => {
		const get = vi.spyOn(api, 'get');
		render(BrowseCarousel, { props: { carousel: continuations, isGuest: true } });
		expect(screen.getByText(/guest accounts have neither/)).toBeInTheDocument();
		expect(get).not.toHaveBeenCalled();
	});

	it('runs a catalogue row for a guest', async () => {
		const get = vi.spyOn(api, 'get').mockResolvedValue([]);
		const fresh: Carousel = { ...continuations, key: 'fresh', params: { airing_status: ['Finished Airing'] } };
		render(BrowseCarousel, { props: { carousel: fresh, isGuest: true } });
		await waitFor(() => expect(get).toHaveBeenCalledWith('/search/anime', expect.anything()));
	});

	it('runs a row over the unrated for a guest, who has rated nothing', async () => {
		const get = vi.spyOn(api, 'get').mockResolvedValue([]);
		const lucky: Carousel = { ...continuations, key: 'lucky-find', params: { rated: ['none', 'in_progress'], sort: 'random' } };
		render(BrowseCarousel, { props: { carousel: lucky, isGuest: true } });
		await waitFor(() => expect(get).toHaveBeenCalledWith('/search/anime', expect.anything()));
		expect((get.mock.calls[0][1] as { params: URLSearchParams }).params.has('rated')).toBe(false);
	});

	it("opens the row's see-all from its title", () => {
		vi.spyOn(api, 'get').mockResolvedValue([]);
		render(BrowseCarousel, { props: { carousel: continuations, isGuest: false } });
		expect(screen.getByRole('link', { name: /Announced continuations/ })).toHaveAttribute(
			'href', '/browse/announced-continuations',
		);
	});

	it("links a home row's tiles back to home", async () => {
		const hit = { uuid: 'abc-123', title: 'Hit', name_eng: null, name_jap: null, media_types: [] };
		vi.spyOn(api, 'get').mockResolvedValue([hit as unknown as AnimeSearchResult]);
		const lucky: Carousel = { ...continuations, key: 'lucky-find', page: 'home' };
		render(BrowseCarousel, { props: { carousel: lucky, isGuest: false } });
		await waitFor(() => expect(screen.getByRole('link', { name: /Hit/ })).toHaveAttribute(
			'href', '/anime?uuid=abc-123&from=home&focus=lucky-find%3Aabc-123',
		));
	});

	it("keeps a home row's results when Browse is left", async () => {
		const get = vi.spyOn(api, 'get').mockResolvedValue([]);
		const fresh: Carousel = { ...continuations, key: 'new-to-catalogue', params: { sort: 'added' }, page: 'home' };
		render(BrowseCarousel, { props: { carousel: fresh, isGuest: false } }).unmount();
		await waitFor(() => expect(get).toHaveBeenCalledTimes(1));
		clearSectionRows();
		render(BrowseCarousel, { props: { carousel: fresh, isGuest: false } });
		await new Promise((resolve) => setTimeout(resolve, 0));
		expect(get).toHaveBeenCalledTimes(1);
	});

	it('runs the same row for a full account', async () => {
		const get = vi.spyOn(api, 'get').mockResolvedValue([]);
		render(BrowseCarousel, { props: { carousel: continuations, isGuest: false } });
		await waitFor(() => expect(get).toHaveBeenCalledWith('/search/anime', expect.anything()));
		expect(screen.queryByText(/guest accounts/)).not.toBeInTheDocument();
	});
});
