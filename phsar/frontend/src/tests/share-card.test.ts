import { describe, it, expect, vi } from 'vitest';
import { render, screen } from '@testing-library/svelte';
import ShareCard from '$lib/components/ShareCard.svelte';
import type { ShareCardBody } from '$lib/utils/shareContent';
import type { RatingOut } from '$lib/types/api';

// The card always mounts a radar, and jsdom has neither canvas nor ResizeObserver — so the
// ECharts loader is stubbed to never resolve. `EChart` then never calls `init`, which keeps
// that out of the assertions below rather than leaving it to lose a race with teardown.
vi.mock('$lib/echarts', () => ({ getEcharts: () => new Promise(() => {}) }));

/**
 * These assertions are about the card's own composition — text, meta lines, score
 * precision, and the pill profile. The radar's own maths lives in the attribute utils.
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

function ratingBody(o: Partial<Extract<ShareCardBody, { kind: 'rating' }>> = {}): ShareCardBody {
	return {
		kind: 'rating',
		score: 8.5,
		ratingStep: 0.5,
		statusLine: '3 of 4 rated',
		ratings: [rating()],
		...o,
	};
}

function infoBody(o: Partial<Extract<ShareCardBody, { kind: 'info' }>> = {}): ShareCardBody {
	return {
		kind: 'info',
		genres: ['Action', 'Drama'],
		ageRating: '17+',
		studios: ['Wit Studio'],
		synopsis: 'Humanity fights for survival behind three walls.',
		...o,
	};
}

const shellProps = {
	title: 'Attack on Titan',
	subtitle: '進撃の巨人',
	coverDataUri: null,
	metaLines: ['TV · Spring 2013 · 25 eps'],
	host: 'phsar.example',
};

const baseProps = { ...shellProps, headerLabel: 'My rating', body: ratingBody() };
const infoProps = { ...shellProps, headerLabel: 'Check this out', body: infoBody() };

describe('ShareCard — the shared shell', () => {
	it('renders the title, meta, status and host', () => {
		render(ShareCard, { props: baseProps });

		expect(screen.getByText('Attack on Titan')).toBeInTheDocument();
		expect(screen.getByText('進撃の巨人')).toBeInTheDocument();
		expect(screen.getByText('TV · Spring 2013 · 25 eps')).toBeInTheDocument();
		expect(screen.getByText('3 of 4 rated')).toBeInTheDocument();
		expect(screen.getByText('phsar.example')).toBeInTheDocument();
	});

	it('falls back to a placeholder when the cover could not be inlined', () => {
		render(ShareCard, { props: baseProps });
		expect(screen.getByText('No image')).toBeInTheDocument();
	});

	it('renders each meta line separately', () => {
		render(ShareCard, {
			props: { ...baseProps, metaLines: ['Fall 2020 - Winter 2026', '64 eps · 1d 2h'] },
		});
		expect(screen.getByText('Fall 2020 - Winter 2026')).toBeInTheDocument();
		expect(screen.getByText('64 eps · 1d 2h')).toBeInTheDocument();
	});

	it('labels the header per variant', () => {
		render(ShareCard, { props: infoProps });
		expect(screen.getByText('Check this out')).toBeInTheDocument();
	});

	it('renders the airing badges under the title', () => {
		render(ShareCard, {
			props: {
				...infoProps,
				badges: [
					{ label: 'Currently Airing', tone: 'airing' as const },
					{ label: 'Story Complete', tone: 'complete' as const },
				],
			},
		});
		expect(screen.getByText('Currently Airing')).toBeInTheDocument();
		expect(screen.getByText('Story Complete')).toBeInTheDocument();
	});
});

describe('ShareCard — rating variant', () => {
	// Proves the card threads ratingStep into the formatter (the rule itself is covered in
	// format-string.test.ts): a 0.5-step user must read "8.0", not "8".
	it('shows the score at the viewer’s step precision', () => {
		render(ShareCard, { props: { ...baseProps, body: ratingBody({ score: 8, ratingStep: 0.5 }) } });
		expect(screen.getByText('8.0')).toBeInTheDocument();
	});

	// Unlike the page's Attribute Summary, the card keeps the whole profile and marks the
	// unrated entries — a standalone artifact should show what wasn't rated. Asserted with a
	// regex because a pill's text content is "Pace: --", so an exact 'Pace:' never matches.
	it('still renders every pill when nothing is rated, marked unset', () => {
		render(ShareCard, { props: baseProps });
		expect(screen.getByText(/^Pace:/)).toBeInTheDocument();
		expect(screen.getByText(/^Originality:/)).toBeInTheDocument();
		expect(screen.getAllByText('--')).toHaveLength(6);
	});

	// not_applicable is auto-set on an unfinished watch, never chosen — an absence of an
	// answer, so it must read as unset rather than as a value.
	it('shows the auto-set not_applicable ending as unset', () => {
		render(ShareCard, {
			props: {
				...baseProps,
				body: ratingBody({ ratings: [rating({ pace: 'fast', ending_type: 'not_applicable' })] }),
			},
		});
		expect(screen.getByText('Fast')).toBeInTheDocument();
		// Pace is answered, so the remaining five pills — ending type among them — read "--".
		expect(screen.getAllByText('--')).toHaveLength(5);
	});

	it('drops the status line when there is none, keeping the score', () => {
		render(ShareCard, { props: { ...baseProps, body: ratingBody({ statusLine: null }) } });
		expect(screen.queryByText('3 of 4 rated')).not.toBeInTheDocument();
		expect(screen.getByText('8.5')).toBeInTheDocument();
	});
});

describe('ShareCard — info variant', () => {
	it('renders the genre chips, age chip, studios and synopsis', () => {
		render(ShareCard, { props: infoProps });

		expect(screen.getByText('Action')).toBeInTheDocument();
		expect(screen.getByText('Drama')).toBeInTheDocument();
		expect(screen.getByText('17+')).toBeInTheDocument();
		expect(screen.getByText('Studio')).toBeInTheDocument();
		expect(screen.getByText('Wit Studio')).toBeInTheDocument();
		expect(
			screen.getByText('Humanity fights for survival behind three walls.'),
		).toBeInTheDocument();
	});

	// The whole point of the second variant: no score, no radar, no attribute pills.
	it('shows none of the rating furniture', () => {
		render(ShareCard, { props: infoProps });
		expect(screen.queryByText('8.5')).not.toBeInTheDocument();
		expect(screen.queryByText(/^Pace:/)).not.toBeInTheDocument();
	});

	// A missing fact must read as missing rather than vanish — an image travels without the
	// app around it, so a dropped studio row is indistinguishable from a rendering bug.
	it('keeps a row for each fact the catalog is missing', () => {
		render(ShareCard, {
			props: { ...infoProps, body: infoBody({ genres: ['--'], ageRating: '--', studios: ['--'] }) },
		});
		expect(screen.getAllByText('--')).toHaveLength(3);
		expect(screen.getByText('Studio')).toBeInTheDocument();
	});

	it('says so when there is no synopsis at all', () => {
		render(ShareCard, { props: { ...infoProps, body: infoBody({ synopsis: null }) } });
		expect(screen.getByText('No synopsis on record.')).toBeInTheDocument();
	});
});
