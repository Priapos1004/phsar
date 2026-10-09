import { describe, it, expect, vi, beforeEach, afterEach } from 'vitest';
import { render, screen, fireEvent } from '@testing-library/svelte';
import SearchBar from '$lib/components/SearchBar.svelte';
import { token } from '$lib/stores/auth';
import { clearFilterOptions } from '$lib/stores/filterOptions';
import type { MediaSearchFilters } from '$lib/utils/search';
import { jsonResponse } from './fixtures/response';

const OPTIONS = {
	genre_name: ['Action', 'Comedy', 'Drama'],
	anime_season: ['Winter 2024', 'Spring 2024'],
	studio_name: ['MAPPA', 'Bones'],
	original_source: ['Manga', 'Original'],
	airing_status: ['Currently Airing', 'Finished Airing'],
	relation_type: ['sequel', 'side_story'],
	media_type: ['TV', 'Movie'],
	age_rating: ['PG-13', 'R'],
	episodes_min: 1,
	episodes_max: 1100,
	score_min: 0,
	score_max: 10,
	scored_by_min: 0,
	// Death Note's vote count: off the log slider's step grid, the phantom-write case.
	scored_by_max: 3_023_456,
	duration_per_episode_min: null,
	duration_per_episode_max: null,
	total_watch_time_min: 60,
	total_watch_time_max: 1_580_000,
};

const BASE: MediaSearchFilters = { query: '', search_type: 'title', view_type: 'anime' };

async function openSheet() {
	await fireEvent.click(screen.getByLabelText('Filters'));
	await screen.findByText('Scored by');
}

describe('SearchBar', () => {
	const originalFetch = globalThis.fetch;

	afterEach(() => {
		globalThis.fetch = originalFetch;
		token.set(null);
	});

	beforeEach(() => {
		// Filter options are cached for the session, so an earlier mount in this file would
		// otherwise serve later ones from cache and they'd observe no fetch at all.
		clearFilterOptions();
		token.set('test-token');
		globalThis.fetch = vi.fn().mockResolvedValue(jsonResponse(OPTIONS));
	});

	it('placeholders follow the view and the mode', () => {
		render(SearchBar, { props: { viewType: 'media' } });
		expect(screen.getByPlaceholderText('Search media...')).toBeInTheDocument();
	});

	it('submits the typed query with the applied filters and mode', async () => {
		const onSearch = vi.fn();
		render(SearchBar, { props: { onSearch, applied: { ...BASE, genre_name: ['Action'] } } });
		const input = screen.getByPlaceholderText('Search anime...');
		await fireEvent.input(input, { target: { value: 'Naruto' } });
		await fireEvent.submit(input.closest('form')!);
		expect(onSearch).toHaveBeenCalledWith(
			expect.objectContaining({ query: 'Naruto', search_type: 'title', genre_name: ['Action'] }),
		);
	});

	it('a mode re-runs the typed query, and waits for one when nothing is typed', async () => {
		const onSearch = vi.fn();
		render(SearchBar, { props: { onSearch } });
		await fireEvent.click(screen.getByRole('button', { name: 'Description' }));
		expect(onSearch).not.toHaveBeenCalled();
		expect(screen.getByPlaceholderText('Describe a story, a character, a theme...')).toBeInTheDocument();

		await fireEvent.input(screen.getByRole('textbox'), { target: { value: 'time travel' } });
		await fireEvent.click(screen.getByRole('button', { name: 'Title' }));
		expect(onSearch).toHaveBeenCalledOnce();
		expect(onSearch).toHaveBeenCalledWith(expect.objectContaining({ query: 'time travel', search_type: 'title' }));
	});

	it('counts the applied filter groups on the filter button', () => {
		render(SearchBar, {
			props: { applied: { ...BASE, genre_name: ['Action'], genre_mode: 'all', top_percent: 20, upcoming_main: false } },
		});
		expect(screen.getByLabelText('Filters')).toHaveTextContent('2');
	});

	it('an untouched sheet applies no range filter', async () => {
		// Opening the sheet must not turn a slider's snap onto its step grid into a filter.
		// Two defences stop it — track ends on the grid (`sliderGrid`) and writing only on
		// commit (DoubleRangeSlider) — and either holds alone, so this fails only with both
		// gone. `sliderGrid`'s own test pins the first.
		const onSearch = vi.fn();
		render(SearchBar, { props: { onSearch, applied: BASE } });
		await openSheet();
		await fireEvent.click(screen.getByRole('button', { name: 'Show results' }));
		const sent = onSearch.mock.calls[0][0];
		for (const key of Object.keys(sent)) expect(key).not.toMatch(/_(min|max)$/);
	});

	it('an unset range reads the catalogue bounds, its thumbs at the track ends', async () => {
		// The bound's own position rounds to 21.5 on a track ending at 21.6: a thumb put
		// there sits a step short of the end and reads 2,965,820.
		render(SearchBar, { props: { applied: BASE } });
		await openSheet();
		expect(screen.getByText('0 – 3,023,456')).toBeInTheDocument();
		const scoredBy = screen.getByText('Scored by').closest('div')!.parentElement!;
		const thumbs = scoredBy.querySelectorAll('[role="slider"]');
		expect([...thumbs].map((t) => t.getAttribute('aria-valuenow'))).toEqual(['0', '21.6']);
	});

	it('a one-sided range comes back as it was sent', async () => {
		const onSearch = vi.fn();
		render(SearchBar, { props: { onSearch, applied: { ...BASE, scored_by_max: 2_965_820 } } });
		await openSheet();
		await fireEvent.click(screen.getByRole('button', { name: 'Show results' }));
		expect(onSearch.mock.calls[0][0]).toMatchObject({ scored_by_max: 2_965_820 });
		expect(onSearch.mock.calls[0][0].scored_by_min).toBeUndefined();
	});

	it('applies staged edits on "Show results" and discards them on dismiss', async () => {
		const onSearch = vi.fn();
		render(SearchBar, { props: { onSearch, applied: BASE } });
		await openSheet();
		await fireEvent.click(screen.getByRole('button', { name: 'Dropped' }));
		await fireEvent.keyDown(document.activeElement ?? document.body, { key: 'Escape' });
		await openSheet();
		expect(screen.getByRole('button', { name: 'Dropped' })).toHaveAttribute('aria-pressed', 'false');

		await fireEvent.click(screen.getByRole('button', { name: 'Dropped' }));
		await fireEvent.click(screen.getByRole('button', { name: 'Show results' }));
		expect(onSearch).toHaveBeenCalledWith(expect.objectContaining({ rated: ['dropped'] }));
	});

	it('a guest gets an explanation in place of the personal filters', async () => {
		render(SearchBar, { context: new Map([['userRole', () => 'restricted_user']]) });
		await openSheet();
		expect(screen.getByText(/Guest accounts have no ratings or watchlist/)).toBeInTheDocument();
		expect(screen.queryByRole('button', { name: 'Dropped' })).not.toBeInTheDocument();
	});

	it('fetches the filter options once per view, not per mount', async () => {
		// SearchBar mounts on both / and /search, and the options only change when the
		// catalogue does.
		const { unmount } = render(SearchBar);
		await openSheet();
		expect(globalThis.fetch).toHaveBeenCalledWith(
			'http://localhost:8000/filters/options?view_type=anime',
			expect.objectContaining({ headers: { Authorization: 'Bearer test-token' } }),
		);
		unmount();

		render(SearchBar);
		await openSheet();
		expect(globalThis.fetch).toHaveBeenCalledTimes(1);
	});
});
