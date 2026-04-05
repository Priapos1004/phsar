import { describe, it, expect, vi } from 'vitest';
import { render, screen } from '@testing-library/svelte';
import RatingCard from '$lib/components/RatingCard.svelte';
import type { RatingOut } from '$lib/types/api';

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

describe('RatingCard', () => {
	it('shows "Rate This" button when no rating exists', () => {
		render(RatingCard, {
			props: {
				mediaUuid: 'media-uuid-1',
	
				totalEpisodes: 12,
				existingRating: null,
				onSaved: vi.fn(),
				onDeleted: vi.fn(),
			},
		});

		expect(screen.getByText('Rate This')).toBeInTheDocument();
		expect(screen.getByText('Share your thoughts')).toBeInTheDocument();
	});

	it('shows rating display with Edit and Delete buttons when rated', () => {
		render(RatingCard, {
			props: {
				mediaUuid: 'media-uuid-1',
	
				totalEpisodes: 12,
				existingRating: mockExistingRating,
				onSaved: vi.fn(),
				onDeleted: vi.fn(),
			},
		});

		expect(screen.getByText('8.5')).toBeInTheDocument();
		expect(screen.getByText(/Edit/)).toBeInTheDocument();
		expect(screen.getByText(/Delete/)).toBeInTheDocument();
	});

	it('displays filled attributes as badges', () => {
		render(RatingCard, {
			props: {
				mediaUuid: 'media-uuid-1',
	
				totalEpisodes: 12,
				existingRating: mockExistingRating,
				onSaved: vi.fn(),
				onDeleted: vi.fn(),
			},
		});

		expect(screen.getByText('Pace: Fast')).toBeInTheDocument();
		expect(screen.getByText('Animation Quality: Good')).toBeInTheDocument();
	});

	it('displays note with quote styling', () => {
		render(RatingCard, {
			props: {
				mediaUuid: 'media-uuid-1',
	
				totalEpisodes: 12,
				existingRating: mockExistingRating,
				onSaved: vi.fn(),
				onDeleted: vi.fn(),
			},
		});

		expect(screen.getByText(/"Great anime"/)).toBeInTheDocument();
	});
});
