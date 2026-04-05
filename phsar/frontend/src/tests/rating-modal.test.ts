import { describe, it, expect, vi } from 'vitest';
import { render, screen } from '@testing-library/svelte';
import RatingModal from '$lib/components/RatingModal.svelte';
import type { RatingOut } from '$lib/types/api';

// Mock API
vi.mock('$lib/api', () => ({
	api: {
		get: vi.fn(),
		post: vi.fn(),
		put: vi.fn(),
		del: vi.fn(),
	},
	ApiError: class extends Error {
		status: number;
		detail: string;
		constructor(status: number, detail: string) {
			super(detail);
			this.name = 'ApiError';
			this.status = status;
			this.detail = detail;
		}
	},
}));

const mockExistingRating: RatingOut = {
	uuid: 'rating-uuid-1',
	rating: 8.5,
	dropped: false,
	episodes_watched: 12,
	note: 'Great anime',
	media_uuid: 'media-uuid-1',
	media_title: 'Test Anime',
	media_cover_image: null,
	anime_uuid: 'anime-uuid-1',
	anime_title: 'Test Anime Series',
	pace: 'fast',
	animation_quality: 'good',
	has_3d_animation: null,
	watched_format: 'sub',
	fan_service: null,
	dialogue_quality: null,
	character_depth: null,
	ending_type: null,
	ending_quality: null,
	story_quality: null,
	originality: null,
	created_at: '2024-01-01T00:00:00',
	modified_at: '2024-01-01T00:00:00',
};

describe('RatingModal', () => {
	it('renders in create mode with Save and Cancel buttons', () => {
		render(RatingModal, {
			props: {
				open: true,
				mediaUuid: 'media-uuid-1',
				mediaTitle: 'Test Anime',
				totalEpisodes: 12,
				existingRating: null,
				onSaved: vi.fn(),
				onDeleted: vi.fn(),

			},
		});

		expect(screen.getByText(/Rate.*Test Anime/)).toBeInTheDocument();
		expect(screen.getByText('Save')).toBeInTheDocument();
		expect(screen.getByText('Cancel')).toBeInTheDocument();
		// No delete button in create mode
		expect(screen.queryByText('Delete')).not.toBeInTheDocument();
	});

	it('renders in edit mode with Delete button', () => {
		render(RatingModal, {
			props: {
				open: true,
				mediaUuid: 'media-uuid-1',
				mediaTitle: 'Test Anime',
				totalEpisodes: 12,
				existingRating: mockExistingRating,
				onSaved: vi.fn(),
				onDeleted: vi.fn(),

			},
		});

		expect(screen.getByText(/Edit Rating.*Test Anime/)).toBeInTheDocument();
		expect(screen.getByText('Delete')).toBeInTheDocument();
		expect(screen.getByText('Save')).toBeInTheDocument();
	});

	it('renders score label', () => {
		render(RatingModal, {
			props: {
				open: true,
				mediaUuid: 'media-uuid-1',
				mediaTitle: 'Test Anime',
				totalEpisodes: null,
				existingRating: null,
				onSaved: vi.fn(),
				onDeleted: vi.fn(),

			},
		});

		expect(screen.getByText(/Score:/)).toBeInTheDocument();
	});

	it('renders note textarea', () => {
		render(RatingModal, {
			props: {
				open: true,
				mediaUuid: 'media-uuid-1',
				mediaTitle: 'Test Anime',
				totalEpisodes: 12,
				existingRating: null,
				onSaved: vi.fn(),
				onDeleted: vi.fn(),

			},
		});

		expect(screen.getByPlaceholderText('Your thoughts on this anime...')).toBeInTheDocument();
	});
});
