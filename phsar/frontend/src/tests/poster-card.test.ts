/**
 * A media poster carries `MediaInfo`'s spoiler guard: a see-all in the media view lists
 * entries past the viewer's frontier, and an anime poster never needs one.
 */
import { describe, it, expect, beforeEach } from 'vitest';
import { render, screen } from '@testing-library/svelte';
import PosterCard from '$lib/components/PosterCard.svelte';
import { spoilerVisibility } from '$lib/stores/spoilerVisibility';
import { userSettings } from '$lib/stores/userSettings';
import type { AnimeSearchResult, MediaSearchResult } from '$lib/types/api';

const base = { uuid: 'm1', title: 'Sequel', name_eng: null, name_jap: null, cover_image: 'https://x.test/c.jpg' };
const media = { ...base, score: 8, scored_by: 10, is_rated: false } as unknown as MediaSearchResult;
const anime = { ...base, avg_score: 8, avg_scored_by: 10, media_types: [] } as unknown as AnimeSearchResult;
const tile = (row: AnimeSearchResult | MediaSearchResult) =>
	render(PosterCard, { props: { row, href: '/x', sort: null } });

beforeEach(() => {
	userSettings.set({ theme: 'default', name_language: 'english', default_search_view: 'anime', rating_step: '0.5', spoiler_level: 'blur' });
	spoilerVisibility.set({ visible_media_uuids: [] });
});

describe('PosterCard', () => {
	it('guards a media cover past the frontier', () => {
		tile(media);
		expect(screen.getByText('Click to reveal')).toBeInTheDocument();
	});

	it('shows a media cover inside the frontier', () => {
		spoilerVisibility.set({ visible_media_uuids: ['m1'] });
		tile(media);
		expect(screen.queryByText('Click to reveal')).not.toBeInTheDocument();
	});

	it('never guards an anime cover', () => {
		tile(anime);
		expect(screen.queryByText('Click to reveal')).not.toBeInTheDocument();
	});
});
