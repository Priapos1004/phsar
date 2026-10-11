import { describe, it, expect, vi, afterEach } from 'vitest';
import { render, screen, waitFor } from '@testing-library/svelte';
import BrowseCarousel from '$lib/components/BrowseCarousel.svelte';
import { api } from '$lib/api';
import type { BrowseCarousel as Carousel } from '$lib/types/api';

const continuations: Carousel = {
	key: 'announced-continuations',
	title: 'Announced continuations',
	params: { upcoming_main: true, rated: ['in_progress', 'on_hold'], sort: 'release' },
	see_all_limit: 1000,
	filter_sets: [],
};

afterEach(() => vi.restoreAllMocks());

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

	it('runs the same row for a full account', async () => {
		const get = vi.spyOn(api, 'get').mockResolvedValue([]);
		render(BrowseCarousel, { props: { carousel: continuations, isGuest: false } });
		await waitFor(() => expect(get).toHaveBeenCalledWith('/search/anime', expect.anything()));
		expect(screen.queryByText(/guest accounts/)).not.toBeInTheDocument();
	});
});
