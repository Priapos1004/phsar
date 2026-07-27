import { describe, it, expect } from 'vitest';
import {
	animeInfoCard,
	animeShareContent,
	mediaInfoCard,
	mediaShareContent,
	SHARE_SYNOPSIS_MAX_CHARS,
	shareSynopsis,
} from '$lib/utils/shareContent';
import type { AnimeDetail, AnimeMediaItem, MediaDetail, RatingOut } from '$lib/types/api';

// Only the catalog/rating fields the builders read are populated, so the fixtures stay
// legible; the partial casts keep them from having to mirror the whole DTOs.
function media(o: Partial<MediaDetail> = {}): MediaDetail {
	return {
		media_type: 'TV',
		anime_season_name: 'Fall',
		anime_season_year: 2020,
		episodes: 24,
		total_watch_time: 34560, // 9h 36m
		cover_image: 'https://cdn.example/media.jpg',
		airing_status: 'Finished Airing',
		genres: [],
		studio: [],
		age_rating_numeric: null,
		description: null,
		...o,
	} as MediaDetail;
}

function member(o: Partial<AnimeMediaItem> = {}): AnimeMediaItem {
	return {
		uuid: 'm1',
		relation_type: 'main',
		airing_status: 'Finished Airing',
		media_type: 'Movie',
		anime_season_name: 'Summer',
		anime_season_year: 2016,
		episodes: 1,
		total_watch_time: 6360, // 1h 46m
		cover_image: 'https://cdn.example/member.jpg',
		...o,
	} as AnimeMediaItem;
}

function anime(o: Partial<AnimeDetail> = {}): AnimeDetail {
	return {
		cover_image: 'https://cdn.example/anime.jpg',
		season_start: 'Fall 2020',
		season_end: null,
		total_episodes: 64,
		total_watch_time: 93600, // 1d 2h
		media: [member()],
		airing_status: 'Finished Airing',
		has_upcoming: false,
		is_finished: false,
		genres: [],
		studios: [],
		age_rating_numeric: null,
		description: null,
		...o,
	} as AnimeDetail;
}

function rating(o: Partial<RatingOut> = {}): RatingOut {
	return {
		media_uuid: 'm1',
		rating: 8.5,
		watch_status: 'completed',
		watched_count: 1,
		episodes_watched: 24,
		...o,
	} as RatingOut;
}

describe('mediaShareContent', () => {
	it('gives the catalog line, the watch status and the media cover', () => {
		const c = mediaShareContent(media(), rating({ watched_count: 7 }));
		expect(c.metaLines).toEqual(['TV · Fall 2020 · 9h 36m']);
		expect(c.statusLine).toBe('Completed · 24/24 eps · watched 7×');
		expect(c.coverUrl).toBe('https://cdn.example/media.jpg');
	});

	it('omits the rewatch count on a first watch', () => {
		expect(mediaShareContent(media(), rating()).statusLine).toBe('Completed · 24/24 eps');
	});

	it('shows a partial watch against the total', () => {
		const c = mediaShareContent(media(), rating({ watch_status: 'on_hold', episodes_watched: 5 }));
		expect(c.statusLine).toBe('On Hold · 5/24 eps');
	});

	it('drops the denominator when the catalog total is unknown (a still-airing show)', () => {
		const c = mediaShareContent(media({ episodes: null }), rating({ episodes_watched: 5 }));
		expect(c.statusLine).toBe('Completed · 5 eps');
	});

	// The episode count belongs on exactly one line — normally the status line...
	it('keeps the count off the catalog line while the status line carries it', () => {
		const c = mediaShareContent(media(), rating());
		expect(c.metaLines[0]).not.toContain('24 eps');
		expect(c.statusLine).toContain('24/24 eps');
	});

	// ...and it must never vanish from both, for a rating predating per-status counts.
	it('falls back to the catalog line when the rating records no count', () => {
		const c = mediaShareContent(media(), rating({ episodes_watched: null }));
		expect(c.metaLines).toEqual(['TV · Fall 2020 · 24 eps · 9h 36m']);
		expect(c.statusLine).toBe('Completed');
	});

	it('drops the season and runtime when the catalog lacks them', () => {
		const c = mediaShareContent(
			media({ anime_season_name: null, anime_season_year: null, total_watch_time: null }),
			rating(),
		);
		expect(c.metaLines).toEqual(['TV']);
	});
});

describe('animeShareContent — one-entry anime', () => {
	// A film reads better as itself than as "1/1 main media".
	it('borrows the media wording, and that media’s cover', () => {
		const c = animeShareContent(anime(), [rating({ episodes_watched: 1 })]);
		expect(c.metaLines).toEqual(['Movie · Summer 2016 · 1h 46m']);
		expect(c.statusLine).toBe('Completed · 1/1 eps');
		expect(c.coverUrl).toBe('https://cdn.example/member.jpg');
	});

	it('falls back to the anime cover when the entry has none', () => {
		const c = animeShareContent(anime({ media: [member({ cover_image: null })] }), [
			rating({ episodes_watched: 1 }),
		]);
		expect(c.coverUrl).toBe('https://cdn.example/anime.jpg');
	});

	// An announced sequel must not flip a film into the franchise shape.
	it('still counts as one entry when the only other media is unaired', () => {
		const withSequel = anime({
			media: [member(), member({ uuid: 'm2', airing_status: 'Not yet aired' })],
		});
		expect(animeShareContent(withSequel, [rating({ episodes_watched: 1 })]).metaLines).toEqual([
			'Movie · Summer 2016 · 1h 46m',
		]);
	});

	it('uses the franchise shape when the sole entry is not the one rated', () => {
		const c = animeShareContent(anime(), [rating({ media_uuid: 'elsewhere' })]);
		expect(c.statusLine).toBe('0/1 main media');
		expect(c.coverUrl).toBe('https://cdn.example/anime.jpg');
	});
});

describe('animeShareContent — franchise', () => {
	const franchise = (media: AnimeMediaItem[], o: Partial<AnimeDetail> = {}) =>
		anime({ media, ...o });

	it('breaks down rated-of-total per relation bucket', () => {
		const c = animeShareContent(
			franchise([
				member({ uuid: 'a', relation_type: 'main' }),
				member({ uuid: 'b', relation_type: 'alternative_version' }),
				member({ uuid: 'c', relation_type: 'side_story' }),
				member({ uuid: 'd', relation_type: 'summary' }),
			]),
			[rating({ media_uuid: 'a' }), rating({ media_uuid: 'd' })],
		);
		// "recap", not "recaps" — the label singularizes on the displayed total.
		expect(c.statusLine).toBe('1/2 main media · 0/1 side media · 1/1 recap');
	});

	// A franchise without recaps shouldn't advertise "0/0 recaps".
	it('omits a bucket the anime has no media in', () => {
		const c = animeShareContent(
			franchise([
				member({ uuid: 'a', relation_type: 'main' }),
				member({ uuid: 'b', relation_type: 'main' }),
			]),
			[rating({ media_uuid: 'a' })],
		);
		expect(c.statusLine).toBe('1/2 main media');
	});

	// Counting an announced sequel would make a finished franchise read as unwatched.
	it('excludes not-yet-aired media from the counts', () => {
		const c = animeShareContent(
			franchise([
				member({ uuid: 'a', relation_type: 'main' }),
				member({ uuid: 'b', relation_type: 'main' }),
				member({ uuid: 'c', relation_type: 'main', airing_status: 'Not yet aired' }),
			]),
			[rating({ media_uuid: 'a' }), rating({ media_uuid: 'b' })],
		);
		expect(c.statusLine).toBe('2/2 main media');
	});

	it('keeps the season and length facts on one line for a single season', () => {
		const c = animeShareContent(
			franchise([member({ uuid: 'a' }), member({ uuid: 'b' })], { season_end: 'Fall 2020' }),
			[rating({ media_uuid: 'a' })],
		);
		expect(c.metaLines).toEqual(['Fall 2020 · 64 eps · 1d 2h']);
	});

	// A range plus the length facts overflows one line on a fixed-width card.
	it('splits the length facts onto their own line for a multi-season range', () => {
		const c = animeShareContent(
			franchise([member({ uuid: 'a' }), member({ uuid: 'b' })], { season_end: 'Winter 2026' }),
			[rating({ media_uuid: 'a' })],
		);
		expect(c.metaLines).toEqual(['Fall 2020 - Winter 2026', '64 eps · 1d 2h']);
	});

	it('drops empty meta lines rather than rendering a blank one', () => {
		const c = animeShareContent(
			franchise([member({ uuid: 'a' }), member({ uuid: 'b' })], {
				season_start: null,
				season_end: null,
				total_episodes: null,
				total_watch_time: null,
			}),
			[rating({ media_uuid: 'a' })],
		);
		expect(c.metaLines).toEqual([]);
	});
});

describe('mediaInfoCard', () => {
	it('carries the episode count up into the meta line', () => {
		// With no status line to hold it, the count belongs on the catalog line.
		expect(mediaInfoCard(media()).metaLines).toEqual(['TV · Fall 2020 · 24 eps · 9h 36m']);
	});

	it('shows a missing fact as missing rather than dropping it', () => {
		const c = mediaInfoCard(
			media({ episodes: null, genres: [], studio: [], age_rating_numeric: null }),
		);
		expect(c.metaLines[0]).toContain('-- eps');
		expect(c.body).toMatchObject({ genres: ['--'], ageRating: '--', studios: ['--'] });
	});

	it('reports the airing status, and never a story-complete badge', () => {
		const c = mediaInfoCard(media({ airing_status: 'Currently Airing' }));
		expect(c.badges).toEqual([{ label: 'Currently Airing', tone: 'airing' }]);
	});

	it('passes the catalog facts through', () => {
		const c = mediaInfoCard(
			media({ genres: ['Action'], studio: ['Bones'], age_rating_numeric: 17, description: 'Hi.' }),
		);
		expect(c.body).toMatchObject({
			kind: 'info',
			genres: ['Action'],
			ageRating: '17+',
			studios: ['Bones'],
			synopsis: 'Hi.',
		});
	});
});

describe('animeInfoCard', () => {
	it('counts the franchise without a numerator, on its own line under the length facts', () => {
		const c = animeInfoCard(
			anime({
				media: [
					member({ uuid: 'a', relation_type: 'main' }),
					member({ uuid: 'b', relation_type: 'main' }),
					member({ uuid: 'c', relation_type: 'summary' }),
				],
			}),
		);
		// Season + length first, then the shape of the franchise — "2 main media", not "0/2".
		expect(c.metaLines).toEqual(['Fall 2020 · 64 eps · 1d 2h', '2 main media · 1 recap']);
	});

	it('borrows the media wording for a one-entry anime, with no rating needed', () => {
		const c = animeInfoCard(anime({ media: [member()] }));
		expect(c.metaLines).toEqual(['Movie · Summer 2016 · 1 ep · 1h 46m']);
		expect(c.coverUrl).toBe('https://cdn.example/member.jpg');
	});

	it('excludes not-yet-aired media from the counts, as the rating card does', () => {
		const c = animeInfoCard(
			anime({
				media: [
					member({ uuid: 'a' }),
					member({ uuid: 'b', airing_status: 'Not yet aired' }),
					member({ uuid: 'c' }),
				],
			}),
		);
		expect(c.metaLines[1]).toBe('2 main media');
	});

	it('badges an upcoming, story-complete anime', () => {
		const c = animeInfoCard(anime({ airing_status: 'Finished Airing', has_upcoming: true, is_finished: true }));
		expect(c.badges).toEqual([
			{ label: 'upcoming content', tone: 'upcoming' },
			{ label: 'Story Complete', tone: 'complete' },
		]);
	});

	it('caps the chip lists and absorbs the remainder into a +N', () => {
		const c = animeInfoCard(
			anime({
				genres: ['a', 'b', 'c', 'd', 'e', 'f', 'g', 'h'],
				studios: ['one', 'two', 'three'],
			}),
		);
		expect(c.body).toMatchObject({
			genres: ['a', 'b', 'c', 'd', 'e', 'f', '+2'],
			studios: ['one', 'two', '+1'],
		});
	});
});

describe('shareSynopsis', () => {
	it('strips MAL attribution and leaves a short synopsis alone', () => {
		expect(shareSynopsis('A short one. [Written by MAL Rewrite]')).toBe('A short one.');
	});

	it('is null when there is nothing left after cleaning', () => {
		expect(shareSynopsis(null)).toBeNull();
		expect(shareSynopsis('[Written by MAL Rewrite]')).toBeNull();
	});

	// The card also line-clamps, but the clamp is a backstop the rasterizer may not honour —
	// so the cut has to be real, and it has to land between words.
	it('cuts an over-long synopsis on a word boundary', () => {
		const long = `${'word '.repeat(200)}end`;
		const cut = shareSynopsis(long)!;
		expect(cut.length).toBeLessThanOrEqual(SHARE_SYNOPSIS_MAX_CHARS + 1);
		expect(cut.endsWith('…')).toBe(true);
		expect(cut).not.toContain('wor…');
	});

	// A CJK synopsis has no spaces to break on; a boundary search would otherwise cut it to
	// a fraction of its allowance, so it falls back to the hard cut.
	it('still fills the budget when there are no word boundaries', () => {
		const cut = shareSynopsis('あ'.repeat(SHARE_SYNOPSIS_MAX_CHARS + 400))!;
		expect(cut.length).toBe(SHARE_SYNOPSIS_MAX_CHARS + 1); // + the ellipsis
	});
});
