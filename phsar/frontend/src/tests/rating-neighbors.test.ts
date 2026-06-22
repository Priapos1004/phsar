import { describe, it, expect } from 'vitest';
import { selectRatingNeighbors } from '$lib/utils/ratingNeighbors';
import type { RatingScoreItem } from '$lib/types/api';

function item(
	o: Partial<RatingScoreItem> & { media_uuid: string; anime_uuid: string; rating: number },
): RatingScoreItem {
	return {
		media_title: o.media_uuid,
		media_name_eng: null,
		media_name_jap: null,
		anime_title: o.anime_uuid,
		anime_name_eng: null,
		anime_name_jap: null,
		media_cover_image: null,
		watch_status: 'completed',
		age_rating_numeric: null,
		genres: [],
		studios: [],
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
		modified_at: '2026-01-01T00:00:00Z',
		...o,
	};
}

const uuids = (items: RatingScoreItem[]) => items.map((i) => i.media_uuid);

describe('selectRatingNeighbors', () => {
	it('picks the 2 closest at-or-below + 2 closest above, excluding the current anime', () => {
		const items = [
			item({ media_uuid: 'self', anime_uuid: 'cur', rating: 5.0 }), // current anime → excluded
			item({ media_uuid: 'a1', anime_uuid: 'A1', rating: 4.0 }),
			item({ media_uuid: 'a2', anime_uuid: 'A2', rating: 4.5 }),
			item({ media_uuid: 'a3', anime_uuid: 'A3', rating: 5.5 }),
			item({ media_uuid: 'a4', anime_uuid: 'A4', rating: 6.0 }),
			item({ media_uuid: 'a5', anime_uuid: 'A5', rating: 7.0 }),
		];

		const { below, above } = selectRatingNeighbors(items, 5.0, { animeUuid: 'cur' });

		// closest below first
		expect(uuids(below)).toEqual(['a2', 'a1']);
		// closest above first; a5 (furthest) drops
		expect(uuids(above)).toEqual(['a3', 'a4']);
		// the current anime's own rating never appears
		expect([...uuids(below), ...uuids(above)]).not.toContain('self');
	});

	it('keeps one rating per anime — the closest to the current score', () => {
		const items = [
			item({ media_uuid: 'x_far', anime_uuid: 'X', rating: 4.0 }),
			item({ media_uuid: 'x_near', anime_uuid: 'X', rating: 4.9 }),
			item({ media_uuid: 'y', anime_uuid: 'Y', rating: 4.5 }),
		];

		const { below } = selectRatingNeighbors(items, 5.0, {});

		// X represented once by its closest member; both X rows never appear together
		expect(uuids(below)).toEqual(['x_near', 'y']);
		expect(uuids(below)).not.toContain('x_far');
	});

	it('breaks score-distance ties by attribute richness, then shared genres', () => {
		const items = [
			item({ media_uuid: 'plain', anime_uuid: 'A', rating: 4.0 }),
			item({
				media_uuid: 'rich',
				anime_uuid: 'B',
				rating: 4.0,
				pace: 'fast',
				animation_quality: 'good',
				story_quality: 'good',
			}),
			item({ media_uuid: 'genre_match', anime_uuid: 'C', rating: 4.0, genres: ['Action'] }),
		];

		const { below, above } = selectRatingNeighbors(items, 5.0, { genres: ['Action'] });

		// All three tie on distance (1.0). Attribute-rich wins, then genre overlap;
		// only 2 slots, so the plain one drops.
		expect(uuids(below)).toEqual(['rich', 'genre_match']);
		expect(above).toEqual([]);
	});

	it('excludes on-hold / dropped ratings — completed only', () => {
		const items = [
			item({ media_uuid: 'dropped', anime_uuid: 'A', rating: 5.0, watch_status: 'dropped' }),
			item({ media_uuid: 'on_hold', anime_uuid: 'B', rating: 5.0, watch_status: 'on_hold' }),
			item({ media_uuid: 'completed', anime_uuid: 'C', rating: 3.0 }),
		];

		const { below } = selectRatingNeighbors(items, 5.0, {});

		// Only the completed rating survives, even though it's further from the score.
		expect(uuids(below)).toEqual(['completed']);
	});

	it('reselects as the score changes (pure — no shared state)', () => {
		const items = [
			item({ media_uuid: 'low', anime_uuid: 'A', rating: 3.0 }),
			item({ media_uuid: 'high', anime_uuid: 'B', rating: 8.0 }),
		];

		const atThree = selectRatingNeighbors(items, 3.0, {});
		expect(uuids(atThree.below)).toEqual(['low']); // 3.0 is at-or-below itself
		expect(uuids(atThree.above)).toEqual(['high']);

		const atEight = selectRatingNeighbors(items, 8.0, {});
		expect(uuids(atEight.below)).toEqual(['high', 'low']); // both now at-or-below 8.0
		expect(atEight.above).toEqual([]);
	});
});
