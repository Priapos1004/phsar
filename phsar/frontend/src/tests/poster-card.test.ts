/**
 * A media poster carries `MediaInfo`'s spoiler guard: a see-all in the media view lists
 * entries past the viewer's frontier, and an anime poster never needs one.
 */
import { describe, it, expect, beforeEach } from 'vitest';
import { cleanup, render, screen } from '@testing-library/svelte';
import PosterCard from '$lib/components/PosterCard.svelte';
import { spoilerVisibility } from '$lib/stores/spoilerVisibility';
import { userSettings } from '$lib/stores/userSettings';
import { watchlistTags } from '$lib/stores/watchlist';
import { REASON_STYLE } from '$lib/utils/recommendation';
import type { AnimeSearchResult, MediaSearchResult } from '$lib/types/api';

const base = { uuid: 'm1', title: 'Sequel', name_eng: null, name_jap: null, cover_image: 'https://x.test/c.jpg' };
const media = { ...base, score: 8, scored_by: 10, is_rated: false } as unknown as MediaSearchResult;
const anime = { ...base, avg_score: 8, avg_scored_by: 10, media_types: [] } as unknown as AnimeSearchResult;
const tile = (row: AnimeSearchResult | MediaSearchResult) =>
	render(PosterCard, { props: { row, href: '/x', sort: null } });

beforeEach(() => {
	userSettings.set({ theme: 'default', name_language: 'english', default_search_view: 'anime', rating_step: '0.5', spoiler_level: 'blur', recommend_hot: true });
	spoilerVisibility.set({ visible_media_uuids: [] });
});

describe('PosterCard', () => {
	it('guards a media cover past the frontier', () => {
		tile(media);
		expect(screen.getByText('Reveal')).toBeInTheDocument();
	});

	it('shows a media cover inside the frontier', () => {
		spoilerVisibility.set({ visible_media_uuids: ['m1'] });
		tile(media);
		expect(screen.queryByText('Reveal')).not.toBeInTheDocument();
	});

	it("names a ranked anime's reason, and nothing for an unranked one", () => {
		const ranked = { ...anime, reason: 'recent', reason_name: 'Frieren' } as AnimeSearchResult;
		tile(ranked);
		expect(screen.getByText('Recent: Because you recently watched “Frieren”')).toBeInTheDocument();
		cleanup();
		tile({ ...ranked, reason: null });
		expect(screen.queryByText(/Frieren/)).not.toBeInTheDocument();
	});

	it("names a watchlist pick's priority and every list its anime is on, each once", () => {
		const entry = (media: string, tag: string) => [media, { media_uuid: media, anime_uuid: 'm1', tag_uuid: tag, tag_name: tag, tag_color: '#000', priority: 2 }] as const;
		watchlistTags.set(new Map([entry('s1', 'Shounen'), entry('s2', 'Isekai'), entry('s3', 'Shounen')]));
		try {
			tile({ ...anime, reason: 'watchlist', reason_name: 'P1' } as AnimeSearchResult);
			expect(screen.getByText("Watchlist: Because it's high priority on “Shounen” & “Isekai”")).toBeInTheDocument();
		} finally {
			watchlistTags.set(new Map());
		}
	});

	it('says when a fresh pick aired, under the heading its age earns', () => {
		const fresh = (name: string | null) => REASON_STYLE.fresh.because(name, []);
		expect(fresh('expected')).toEqual({ text: 'Because its finale is estimated to be days away' });
		// In the last month, so the context places it: no year, even across New Year.
		expect(fresh('finished:2025-12-28')).toEqual({ text: 'Because it finished airing on Dec 28' });
		expect(fresh('finished-year')).toEqual({ text: 'Because it finished airing in the past year', label: 'Fresh' });
		expect(fresh('started-5y')).toEqual({ text: 'Because it started airing two to five years ago', label: 'Era' });
		expect(fresh('finished-old')).toEqual({ text: 'Because it finished airing over ten years ago', label: 'Classic' });
		expect(fresh(null)).toEqual({ text: "Because it's as fresh as what you usually pick" });
	});

	it('reads a ranked tile under the heading its reason gives', () => {
		tile({ ...anime, reason: 'fresh', reason_name: 'finished-old' } as AnimeSearchResult);
		expect(screen.getByText('Classic: Because it finished airing over ten years ago')).toBeInTheDocument();
	});

	it('never guards an anime cover', () => {
		tile(anime);
		expect(screen.queryByText('Reveal')).not.toBeInTheDocument();
	});
});
