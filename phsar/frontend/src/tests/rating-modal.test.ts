import { describe, it, expect, vi } from 'vitest';
import { render, screen, fireEvent } from '@testing-library/svelte';
import RatingCard from '$lib/components/RatingCard.svelte';
import { api } from '$lib/api';
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
	watch_status: 'completed',
	watched_count: 1,
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

	it('shows the On Hold badge for an on_hold rating', () => {
		render(RatingCard, {
			props: {
				mediaUuid: 'media-uuid-1',
				totalEpisodes: 12,
				existingRating: { ...mockExistingRating, watch_status: 'on_hold' },
				onSaved: vi.fn(),
				onDeleted: vi.fn(),
			},
		});

		expect(screen.getByText('On Hold')).toBeInTheDocument();
	});

	it('shows the watched-count badge once rewatched', () => {
		render(RatingCard, {
			props: {
				mediaUuid: 'media-uuid-1',
				totalEpisodes: 12,
				existingRating: { ...mockExistingRating, watched_count: 3 },
				onSaved: vi.fn(),
				onDeleted: vi.fn(),
			},
		});

		expect(screen.getByText(/Watched 3/)).toBeInTheDocument();
	});

	it('logs a rewatch only after confirming in the pop-up', async () => {
		vi.mocked(api.post).mockResolvedValue({ ...mockExistingRating, watched_count: 2 });
		const onSaved = vi.fn();
		render(RatingCard, {
			props: {
				mediaUuid: 'media-uuid-1',
				totalEpisodes: 12,
				existingRating: mockExistingRating,
				onSaved,
				onDeleted: vi.fn(),
			},
		});

		// Opening the confirm pop-up does NOT call the API
		await fireEvent.click(screen.getByText('Rewatch'));
		expect(api.post).not.toHaveBeenCalled();
		expect(screen.getByText('Log a rewatch?')).toBeInTheDocument();

		// Confirming in the dialog hits the rewatch endpoint
		await fireEvent.click(screen.getByText('Log rewatch'));
		expect(api.post).toHaveBeenCalledWith('/ratings/rating-uuid-1/rewatch', {});
	});

	it('does not offer rewatch for a dropped rating', () => {
		render(RatingCard, {
			props: {
				mediaUuid: 'media-uuid-1',
				totalEpisodes: 12,
				existingRating: { ...mockExistingRating, watch_status: 'dropped' },
				onSaved: vi.fn(),
				onDeleted: vi.fn(),
			},
		});

		expect(screen.queryByText('Rewatch')).not.toBeInTheDocument();
	});
});
