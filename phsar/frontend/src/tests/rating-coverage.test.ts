import { describe, it, expect, afterEach } from 'vitest';
import { render } from '@testing-library/svelte';
import { COVERAGE_STYLE } from '$lib/utils/ratingCoverage';
import { ratingCoverage, clearRatingCoverage } from '$lib/stores/ratingCoverage';
import RatedAnimeCard from '$lib/components/ratings/RatedAnimeCard.svelte';
import MediaInfo from '$lib/components/MediaInfo.svelte';
import type { CoverageTier } from '$lib/types/api';
import type { AnimeRatingRow } from '$lib/utils/ratingStats';

const TIERS: CoverageTier[] = ['some', 'main', 'all'];
const METALS = ['main', 'all'] as const;

// The store outlives every component that reads it.
afterEach(() => clearRatingCoverage());

describe('COVERAGE_STYLE', () => {
	it('gives the metal tiers a second tone and the base tier the theme token', () => {
		// The hairline is what keeps a near-black or gold edge visible against both
		// the light and the dark page background.
		for (const tier of METALS) expect(COVERAGE_STYLE[tier].hairline).toBeTruthy();
		expect(COVERAGE_STYLE.some.edge).toContain('var(--primary)');
		expect(COVERAGE_STYLE.some.hairline).toBeUndefined();
	});

	it('keeps each band readable against the text colour it carries', () => {
		// Obsidian takes light text, gold takes dark. Getting this backwards is the
		// one way a tinted footer becomes unreadable, and jsdom cannot see it.
		const lum = (hex: string) => {
			const n = parseInt(hex.slice(1), 16);
			return 0.299 * ((n >> 16) & 255) + 0.587 * ((n >> 8) & 255) + 0.114 * (n & 255);
		};
		for (const tier of METALS) {
			const stops = [...COVERAGE_STYLE[tier].band.matchAll(/#([0-9a-f]{6})/g)].map((m) =>
				lum('#' + m[1])
			);
			const mid = (Math.max(...stops) + Math.min(...stops)) / 2;
			expect(Math.abs(lum(COVERAGE_STYLE[tier].foreground!) - mid)).toBeGreaterThan(80);
		}
	});

	it('labels every tier distinctly', () => {
		expect(new Set(TIERS.map((t) => COVERAGE_STYLE[t].label)).size).toBe(TIERS.length);
	});
});

describe('RatedAnimeCard coverage marking', () => {
	const row = (over: Partial<AnimeRatingRow> = {}) =>
		({
			anime_uuid: 'anime-1',
			detailUuid: 'anime-1',
			title: 'Fixture',
			name_eng: null,
			name_jap: null,
			cover_image: null,
			userScore: 8,
			mainCount: 1,
			sideCount: 0,
			relationLabel: null,
			statusBadge: null,
			...over
		}) as unknown as AnimeRatingRow;

	const mark = (over: Partial<AnimeRatingRow> = {}) =>
		render(RatedAnimeCard, {
			props: { row: row(over), nameLanguage: 'english' as const, scoreDecimals: 1 }
		}).container.querySelector('[data-coverage]');

	it('marks nothing for an anime the store has no tier for', () => {
		expect(mark()).toBeNull();
	});

	it('marks nothing for the base tier, which every card here already is', () => {
		ratingCoverage.set(new Map([['anime-1', 'some']]));
		expect(mark()).toBeNull();
	});

	it.each(METALS)('marks the card with its tier (%s)', (tier) => {
		ratingCoverage.set(new Map([['anime-1', tier]]));
		const el = mark() as HTMLElement;
		expect(el.getAttribute('data-coverage')).toBe(tier);
		// An outline, not a box-shadow: it hugs the card, and it does not displace
		// the composed `shadow-sm` + `group-hover:` chain the card relies on.
		expect(el.style.outline).toBe(`2px solid ${COVERAGE_STYLE[tier].edge}`);
		expect(el.style.boxShadow).toBe('');
		expect(el.className).toContain('group-hover:shadow-md');
	});

	it('leaves a media-grain row unmarked even when its anime is complete', () => {
		// `anime_uuid` is the PARENT anime at media grain, so without the guard one
		// rated side story inherits the franchise tier — and so does every sibling.
		ratingCoverage.set(new Map([['anime-1', 'all']]));
		expect(mark({ media_uuid: 'media-9', detailUuid: 'media-9' })).toBeNull();
	});
});

describe('MediaInfo coverage marking', () => {
	const mount = (props: Record<string, unknown>) =>
		render(MediaInfo, {
			props: {
				info_type: 'anime',
				title: 'Fixture',
				airing_status: 'Finished Airing',
				media_uuid: 'anime-1',
				...props
			}
		}).container;

	it('leaves an unrated anime card unmarked', () => {
		expect(mount({}).querySelector('.coverage-band')).toBeNull();
	});

	it.each(TIERS)('bands the anime card at its tier (%s)', (tier) => {
		ratingCoverage.set(new Map([['anime-1', tier]]));
		const band = mount({}).querySelector('.coverage-band');
		expect(band!.getAttribute('aria-label')).toBe(COVERAGE_STYLE[tier].label);
	});

	it('bands a rated media card at the base tier, never above it', () => {
		// Seeded with a metal tier under this uuid so the assertion fails if the grain
		// check is dropped; the store is keyed by ANIME uuid, so it never hits for real.
		ratingCoverage.set(new Map([['anime-1', 'all']]));
		const band = mount({ info_type: 'media', is_rated: true }).querySelector('.coverage-band');
		expect(band!.getAttribute('aria-label')).toBe(COVERAGE_STYLE.some.label);
	});

	it('leaves an unrated media card unmarked', () => {
		expect(
			mount({ info_type: 'media', is_rated: false }).querySelector('.coverage-band')
		).toBeNull();
	});
});
