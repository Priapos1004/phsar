import { describe, it, expect, vi, beforeEach, afterEach } from 'vitest';
import { render, screen, fireEvent } from '@testing-library/svelte';
import SearchBar from '$lib/components/SearchBar.svelte';
import { token } from '$lib/stores/auth';

describe('SearchBar', () => {
	const originalFetch = global.fetch;

	afterEach(() => {
		global.fetch = originalFetch;
		token.set(null);
	});

	beforeEach(() => {
		// Set token in store (used by api client)
		token.set('test-token');

		// Mock the filter options API call
		global.fetch = vi.fn().mockResolvedValue({
			ok: true,
			json: () =>
				Promise.resolve({
					genre_name: ['Action', 'Comedy', 'Drama'],
					anime_season: ['Winter 2024', 'Spring 2024'],
					studio_name: ['MAPPA', 'Bones'],
					airing_status: ['Currently Airing', 'Finished Airing'],
					relation_type: ['Sequel', 'Prequel'],
					media_type: ['TV', 'Movie'],
					age_rating: ['PG-13', 'R'],
					episodes_min: 1,
					episodes_max: 100,
					score_min: 0,
					score_max: 10,
					scored_by_min: 0,
					scored_by_max: 1000000,
					duration_per_episode_min: 60,
					duration_per_episode_max: 7200,
					total_watch_time_min: 60,
					total_watch_time_max: 360000,
				}),
		});
	});

	it('renders search input with placeholder', () => {
		render(SearchBar);
		expect(screen.getByPlaceholderText('Search anime...')).toBeInTheDocument();
	});

	it('renders with media placeholder when viewType is media', () => {
		render(SearchBar, { props: { viewType: 'media' } });
		expect(screen.getByPlaceholderText('Search media...')).toBeInTheDocument();
	});

	it('has a filter toggle button', () => {
		render(SearchBar);
		expect(screen.getByLabelText('Toggle filters')).toBeInTheDocument();
	});

	it('filter panel is hidden by default', () => {
		render(SearchBar);
		expect(screen.queryByText('Filters')).not.toBeInTheDocument();
	});

	it('shows filter panel when toggle is clicked', async () => {
		render(SearchBar);
		await fireEvent.click(screen.getByLabelText('Toggle filters'));
		expect(screen.getByText('Filters')).toBeInTheDocument();
	});

	it('shows "Expand search to descriptions" checkbox in filter panel', async () => {
		render(SearchBar);
		await fireEvent.click(screen.getByLabelText('Toggle filters'));
		expect(screen.getByLabelText('Expand search to descriptions')).toBeInTheDocument();
	});

	it('calls onSearch with query params on form submit', async () => {
		const onSearch = vi.fn();
		render(SearchBar, { props: { onSearch } });

		const input = screen.getByPlaceholderText('Search anime...');
		await fireEvent.input(input, { target: { value: 'Naruto' } });

		// Submit via hidden submit button
		const form = input.closest('form')!;
		await fireEvent.submit(form);

		expect(onSearch).toHaveBeenCalledWith(
			expect.objectContaining({
				query: 'Naruto',
				search_type: 'title',
			})
		);
	});

	it('sets search_type to description when checkbox is checked', async () => {
		const onSearch = vi.fn();
		render(SearchBar, { props: { onSearch } });

		// Open filters and check the checkbox
		await fireEvent.click(screen.getByLabelText('Toggle filters'));
		await fireEvent.click(screen.getByLabelText('Expand search to descriptions'));

		// Submit
		const form = screen.getByPlaceholderText('Search anime...').closest('form')!;
		await fireEvent.submit(form);

		expect(onSearch).toHaveBeenCalledWith(
			expect.objectContaining({
				search_type: 'description',
			})
		);
	});

	it('fetches filter options on mount', async () => {
		render(SearchBar);

		await vi.waitFor(() => {
			expect(global.fetch).toHaveBeenCalledWith(
				'http://localhost:8000/filters/options?view_type=anime',
				expect.objectContaining({
					headers: { Authorization: 'Bearer test-token' },
				})
			);
		});
	});
});
