import { describe, it, expect, vi, beforeEach } from 'vitest';
import { render, screen, fireEvent } from '@testing-library/svelte';
import MediaDetailPage from '../routes/media/+page.svelte';
import type { MediaDetail } from '$lib/types/api';

// Mock setContext/getContext
const mockGetUserRole = vi.fn(() => 'user');
vi.mock('svelte', async () => {
	const actual = await vi.importActual('svelte');
	return {
		...actual,
		getContext: () => mockGetUserRole,
		setContext: vi.fn(),
	};
});

// Mock page state with uuid param
vi.mock('$app/state', () => ({
	page: {
		url: new URL('http://localhost:5173/media?uuid=test-uuid-123'),
		params: {},
		route: { id: '/media' },
		status: 200,
		error: null,
		data: {},
		form: null,
	},
}));

const mockMediaDetail: MediaDetail = {
	uuid: 'test-uuid-123',
	mal_id: 1,
	mal_url: 'https://myanimelist.net/anime/1',
	title: 'Test Anime',
	name_eng: 'Test Anime English',
	name_jap: 'テストアニメ',
	other_names: [],
	media_type: 'TV',
	relation_type: 'main',
	age_rating: 'PG-13',
	description: 'A great anime about testing things in a world of code.',
	original_source: 'Manga',
	cover_image: 'https://example.com/cover.jpg',
	score: 8.42,
	scored_by: 12340,
	episodes: 12,
	anime_season_name: 'Spring',
	anime_season_year: 2024,
	airing_status: 'Finished Airing',
	aired_from: '2024-04-01',
	aired_to: '2024-06-24',
	duration: '24 min per ep',
	duration_seconds: 1440,
	genres: ['Action', 'Drama'],
	studio: ['MAPPA'],
	anime_uuid: 'anime-uuid-1',
	anime_title: 'Test Anime Series',
	anime_name_eng: null,
	anime_name_jap: null,
	anime_other_names: [],
	total_watch_time: 17280,
	age_rating_numeric: 13,
	sibling_media: [
		{
			uuid: 'sibling-uuid-1',
			title: 'Test OVA',
			name_eng: null,
			cover_image: null,
			media_type: 'OVA',
			relation_type: 'other',
			episodes: 2,
			airing_status: 'Finished Airing',
			anime_season_name: 'Fall',
			anime_season_year: 2024,
		},
	],
};

// Mock API
vi.mock('$lib/api', () => {
	const ApiError = class extends Error {
		status: number;
		detail: string;
		constructor(status: number, detail: string) {
			super(detail);
			this.name = 'ApiError';
			this.status = status;
			this.detail = detail;
		}
	};
	return {
		api: {
			get: vi.fn(),
			post: vi.fn(),
			put: vi.fn(),
			del: vi.fn(),
		},
		ApiError,
	};
});

describe('Media Detail Page', () => {
	beforeEach(async () => {
		const { api } = await import('$lib/api');
		vi.mocked(api.get).mockImplementation(async (path: string) => {
			if (path.startsWith('/media/')) return mockMediaDetail;
			if (path.startsWith('/ratings/media/')) {
				const { ApiError } = await import('$lib/api');
				throw new ApiError(404, 'Rating not found');
			}
			return null;
		});
		mockGetUserRole.mockReturnValue('user');
	});

	it('renders media title and English name', async () => {
		render(MediaDetailPage);
		// Wait for async load
		await vi.waitFor(() => {
			expect(screen.getByText('Test Anime English')).toBeInTheDocument();
		});
	});

	it('renders description', async () => {
		render(MediaDetailPage);
		await vi.waitFor(() => {
			expect(screen.getByText(/A great anime about testing/)).toBeInTheDocument();
		});
	});

	it('renders genre badges', async () => {
		render(MediaDetailPage);
		await vi.waitFor(() => {
			expect(screen.getByText('Action')).toBeInTheDocument();
			expect(screen.getByText('Drama')).toBeInTheDocument();
		});
	});

	it('renders sibling media in carousel', async () => {
		render(MediaDetailPage);
		await vi.waitFor(() => {
			expect(screen.getByText('Test OVA')).toBeInTheDocument();
		});
	});

	it('shows "Rate This" button when no rating exists', async () => {
		render(MediaDetailPage);
		await vi.waitFor(() => {
			expect(screen.getByText('Rate This')).toBeInTheDocument();
		});
	});

	it('disables buttons for restricted user', async () => {
		mockGetUserRole.mockReturnValue('restricted_user');
		render(MediaDetailPage);
		await vi.waitFor(() => {
			const rateButton = screen.getByText('Rate This').closest('button');
			expect(rateButton).toBeDisabled();
		});
	});

	it('renders MAL score', async () => {
		render(MediaDetailPage);
		await vi.waitFor(() => {
			expect(screen.getByText('8.42')).toBeInTheDocument();
		});
	});
});
