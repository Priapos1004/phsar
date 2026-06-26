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
		anime_cover_image: null,
		watch_status: 'completed',
		age_rating_numeric: null,
		genres: [],
		studios: [],
		mal_score: null,
		scored_by: 0,
		episodes: null,
		total_watch_time: null,
		anime_season_name: null,
		anime_season_year: null,
		relation_type: 'main',
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

const uuids = (items: RatingScoreItem[]) => items.map((i) => i.media_uuid);

describe('selectRatingNeighbors', () => {
	it('with ≥2 same-score ratings → 2 equal + 1 lower + 1 higher, excluding the current anime', () => {
		const items = [
			item({ media_uuid: 'self', anime_uuid: 'cur', rating: 5.0 }), // current anime → excluded
			item({ media_uuid: 'e1', anime_uuid: 'E1', rating: 5.0 }),
			item({ media_uuid: 'e2', anime_uuid: 'E2', rating: 5.0 }),
			item({ media_uuid: 'e3', anime_uuid: 'E3', rating: 5.0 }), // 3rd equal — capped out
			item({ media_uuid: 'lo_near', anime_uuid: 'L1', rating: 4.5 }),
			item({ media_uuid: 'lo_far', anime_uuid: 'L2', rating: 4.0 }),
			item({ media_uuid: 'hi_near', anime_uuid: 'H1', rating: 5.5 }),
			item({ media_uuid: 'hi_far', anime_uuid: 'H2', rating: 6.0 }),
		];

		// equal capped at 2 (stable input order), then the closest lower + closest higher.
		expect(uuids(selectRatingNeighbors(items, 5.0, { animeUuid: 'cur' }))).toEqual([
			'e1',
			'e2',
			'lo_near',
			'hi_near',
		]);
	});

	it('with exactly 1 same-score rating → 1 lower + 1 equal + 2 higher (odd slot prefers higher)', () => {
		const items = [
			item({ media_uuid: 'eq', anime_uuid: 'E', rating: 5.0 }),
			item({ media_uuid: 'lo', anime_uuid: 'L1', rating: 4.5 }),
			item({ media_uuid: 'lo2', anime_uuid: 'L2', rating: 4.0 }),
			item({ media_uuid: 'hi1', anime_uuid: 'H1', rating: 5.5 }),
			item({ media_uuid: 'hi2', anime_uuid: 'H2', rating: 6.0 }),
			item({ media_uuid: 'hi3', anime_uuid: 'H3', rating: 7.0 }),
		];

		// 1 equal taken; the 3 remaining slots split 1 lower / 2 higher.
		expect(uuids(selectRatingNeighbors(items, 5.0, {}))).toEqual(['eq', 'lo', 'hi1', 'hi2']);
	});

	it('with no same-score rating → 2 lower + 2 higher (even split)', () => {
		const items = [
			item({ media_uuid: 'lo1', anime_uuid: 'L1', rating: 4.5 }),
			item({ media_uuid: 'lo2', anime_uuid: 'L2', rating: 4.0 }),
			item({ media_uuid: 'lo3', anime_uuid: 'L3', rating: 3.0 }),
			item({ media_uuid: 'hi1', anime_uuid: 'H1', rating: 5.5 }),
			item({ media_uuid: 'hi2', anime_uuid: 'H2', rating: 6.0 }),
			item({ media_uuid: 'hi3', anime_uuid: 'H3', rating: 7.0 }),
		];

		expect(uuids(selectRatingNeighbors(items, 5.0, {}))).toEqual(['lo1', 'lo2', 'hi1', 'hi2']);
	});

	it('treats float-noisy scores within the equality epsilon as the same score', () => {
		const items = [
			item({ media_uuid: 'noisy', anime_uuid: 'E', rating: 5.000000001 }), // ~= 5.0
			item({ media_uuid: 'step_up', anime_uuid: 'H', rating: 5.01 }), // 0.01 apart → higher
			item({ media_uuid: 'lo', anime_uuid: 'L', rating: 4.99 }), // 0.01 apart → lower
		];

		// noisy reads as equal; 5.01 / 4.99 stay in their own groups.
		const result = uuids(selectRatingNeighbors(items, 5.0, {}));
		expect(result).toContain('noisy');
		expect(result).toContain('step_up');
		expect(result).toContain('lo');
		// equal first in the returned order
		expect(result[0]).toBe('noisy');
	});

	it('backfills the other side when one side runs out (higher exhausted → extra lower)', () => {
		const items = [
			item({ media_uuid: 'lo1', anime_uuid: 'L1', rating: 4.9 }),
			item({ media_uuid: 'lo2', anime_uuid: 'L2', rating: 4.5 }),
			item({ media_uuid: 'lo3', anime_uuid: 'L3', rating: 4.0 }),
			item({ media_uuid: 'lo4', anime_uuid: 'L4', rating: 3.0 }),
			item({ media_uuid: 'hi1', anime_uuid: 'H1', rating: 5.5 }), // only one higher
		];

		// Even split wants 2/2; only 1 higher exists, so the 4th slot backfills a 3rd lower.
		expect(uuids(selectRatingNeighbors(items, 5.0, {}))).toEqual(['lo1', 'lo2', 'lo3', 'hi1']);
	});

	it('keeps one rating per anime — the closest to the current score', () => {
		const items = [
			item({ media_uuid: 'x_far', anime_uuid: 'X', rating: 4.0 }),
			item({ media_uuid: 'x_near', anime_uuid: 'X', rating: 4.9 }),
			item({ media_uuid: 'y', anime_uuid: 'Y', rating: 4.5 }),
		];

		// X represented once by its closest member; both X rows never appear together.
		const result = uuids(selectRatingNeighbors(items, 5.0, {}));
		expect(result).toEqual(['x_near', 'y']);
		expect(result).not.toContain('x_far');
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
			item({ media_uuid: 'hi1', anime_uuid: 'D', rating: 5.5 }),
			item({ media_uuid: 'hi2', anime_uuid: 'E', rating: 6.0 }),
		];

		// 2 lower slots among the three 4.0 ties: attribute-rich wins, then genre overlap;
		// 'plain' drops. The two highers fill the rest.
		const result = uuids(selectRatingNeighbors(items, 5.0, { genres: ['Action'] }));
		expect(result).toEqual(['rich', 'genre_match', 'hi1', 'hi2']);
		expect(result).not.toContain('plain');
	});

	it('excludes on-hold / dropped ratings — completed only', () => {
		const items = [
			item({ media_uuid: 'dropped', anime_uuid: 'A', rating: 5.0, watch_status: 'dropped' }),
			item({ media_uuid: 'on_hold', anime_uuid: 'B', rating: 5.0, watch_status: 'on_hold' }),
			item({ media_uuid: 'completed', anime_uuid: 'C', rating: 3.0 }),
		];

		// Only the completed rating survives, even though it's further from the score.
		expect(uuids(selectRatingNeighbors(items, 5.0, {}))).toEqual(['completed']);
	});

	it('reselects as the score changes (pure — no shared state)', () => {
		const items = [
			item({ media_uuid: 'low', anime_uuid: 'A', rating: 3.0 }),
			item({ media_uuid: 'high', anime_uuid: 'B', rating: 8.0 }),
		];

		// At 3.0: 'low' is equal, 'high' is the only higher.
		expect(uuids(selectRatingNeighbors(items, 3.0, {}))).toEqual(['low', 'high']);
		// At 8.0: 'high' is equal, 'low' is the only lower (equal listed first).
		expect(uuids(selectRatingNeighbors(items, 8.0, {}))).toEqual(['high', 'low']);
	});
});
