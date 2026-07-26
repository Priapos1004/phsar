import { describe, it, expect } from 'vitest';
import { render, screen } from '@testing-library/svelte';
import ShareCard from '$lib/components/ShareCard.svelte';
import type { RatingOut } from '$lib/types/api';

/**
 * Fixtures deliberately leave the five *quality* attributes unset, so `AttributeRadar`
 * short-circuits and no ECharts instance mounts — jsdom has neither canvas nor
 * ResizeObserver. The radar's own averaging is covered by the attribute utils; what
 * matters here is the card's own composition and its no-attributes degradation.
 */
function rating(o: Partial<RatingOut> = {}): RatingOut {
	return {
		uuid: 'r1',
		rating: 8.5,
		watch_status: 'completed',
		watched_count: 1,
		episodes_watched: 24,
		note: null,
		media_uuid: 'm1',
		media_title: 'Season 1',
		media_cover_image: null,
		anime_uuid: 'a1',
		anime_title: 'Some Anime',
		pace: null,
		animation_quality: null,
		has_3d_animation: null,
		watched_format: null,
		fan_service: null,
		dialogue_quality: null,
		character_depth: null,
		ending_type: null,
		ending_quality: null,
		story_quality: null,
		originality: null,
		created_at: '2026-01-01T00:00:00Z',
		modified_at: '2026-01-01T00:00:00Z',
		...o,
	};
}

const baseProps = {
	title: 'Attack on Titan',
	subtitle: '進撃の巨人',
	coverDataUri: null,
	meta: 'TV · Spring 2013 · 25 eps',
	score: 8.5,
	ratingStep: 0.5,
	statusLine: '3 of 4 rated',
	ratings: [rating()],
	host: 'phsar.example',
};

describe('ShareCard', () => {
	it('renders the title, meta, status and host', () => {
		render(ShareCard, { props: baseProps });

		expect(screen.getByText('Attack on Titan')).toBeInTheDocument();
		expect(screen.getByText('進撃の巨人')).toBeInTheDocument();
		expect(screen.getByText('TV · Spring 2013 · 25 eps')).toBeInTheDocument();
		expect(screen.getByText('3 of 4 rated')).toBeInTheDocument();
		expect(screen.getByText('phsar.example')).toBeInTheDocument();
	});

	// Proves the card threads ratingStep into the formatter (the rule itself is covered in
	// format-string.test.ts): a 0.5-step user must read "8.0", not "8".
	it('shows the score at the viewer’s step precision', () => {
		render(ShareCard, { props: { ...baseProps, score: 8, ratingStep: 0.5 } });
		expect(screen.getByText('8.0')).toBeInTheDocument();
	});

	it('falls back to a placeholder when the cover could not be inlined', () => {
		render(ShareCard, { props: baseProps });
		expect(screen.getByText('No image')).toBeInTheDocument();
	});

	it('renders the attribute pills when a categorical attribute is rated', () => {
		render(ShareCard, { props: { ...baseProps, ratings: [rating({ pace: 'fast' })] } });
		expect(screen.getByText(/^Pace:/)).toBeInTheDocument();
		expect(screen.getByText('Fast')).toBeInTheDocument();
	});

	// Nothing rated → no radar, no pills, and crucially no empty gap on the card. Asserted
	// with a regex because a pill's text content is "Pace: --" — an exact 'Pace:' query
	// would find nothing whether or not the block rendered.
	it('drops the attribute block when no attribute is rated', () => {
		render(ShareCard, { props: baseProps });
		expect(screen.queryByText(/^Pace:/)).not.toBeInTheDocument();
	});

	// A rating whose only attribute is the auto-set not_applicable ending is "unrated".
	it('treats the not_applicable sentinel as no attributes', () => {
		render(ShareCard, {
			props: { ...baseProps, ratings: [rating({ ending_type: 'not_applicable' })] },
		});
		expect(screen.queryByText(/^Ending Type:/)).not.toBeInTheDocument();
	});

	it('omits the score circle when there is no score', () => {
		render(ShareCard, { props: { ...baseProps, score: null, statusLine: null } });
		expect(screen.queryByText('8.5')).not.toBeInTheDocument();
		expect(screen.getByText('Attack on Titan')).toBeInTheDocument();
	});
});
