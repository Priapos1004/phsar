// The readiness rules, case by case. docs/features/readiness.md carries the same table
// in prose; this is the executable copy, and the one that fails when a rule moves.
import { describe, it, expect } from 'vitest';
import { watchlistItem as item, NOW } from './fixtures/watchlistItem';
import {
	animeStatus,
	isAvailable,
	isReady,
	mediaClass,
	statusByAnime,
	STANDALONE_SECONDS,
} from '$lib/utils/watchlistReady';
import { filterByReadiness, filterByTags } from '$lib/utils/watchlistStats';
import { nextSeasonKey, seasonKey } from '$lib/utils/getSeason';
import type { WatchlistItem } from '$lib/types/api';
import readinessCases from './fixtures/readiness-cases.json';

const aired = (o = {}) => item({ airing_status: 'Finished Airing', ...o });
const airing = (o = {}) => item({ airing_status: 'Currently Airing', ...o });
const unaired = (season: string | null, year: number | null, o = {}) =>
	item({ airing_status: 'Not yet aired', anime_season_name: season, anime_season_year: year, ...o });

describe('seasonKey / nextSeasonKey', () => {
	it('encodes a season the way the backend does', () => {
		// The backend half of this pins the same literal in
		// tests/routers/test_watchlist.py::test_franchise_upcoming_key_takes_the_earliest_announced_season.
		// No import spans Python and TypeScript, so these two assertions are the only
		// thing holding the encoding together — change one and change the other.
		expect(seasonKey('Fall', 2026)).toBe(2026 * 10 + 4);
		expect(seasonKey('Winter', 2027)).toBe(2027 * 10 + 1);
		expect(seasonKey('Fall', 2026)!).toBeLessThan(seasonKey('Winter', 2027)!);
	});

	it('has no key for an unknown season, rather than one that sorts first', () => {
		expect(seasonKey(null, 2027)).toBeNull();
		expect(seasonKey('Fall', null)).toBeNull();
	});

	it('rolls Fall into the next Winter', () => {
		expect(nextSeasonKey(new Date('2026-08-15'))).toBe(seasonKey('Fall', 2026));
		expect(nextSeasonKey(new Date('2026-11-15'))).toBe(seasonKey('Winter', 2027));
	});
});

describe('mediaClass', () => {
	it.each([
		['finished → aired', aired(), 'aired'],
		['airing now', airing(), 'airing'],
		['this season, still marked unaired (stale scrape)', unaired('Summer', 2026), 'soon'],
		['next season', unaired('Fall', 2026), 'soon'],
		['two seasons out', unaired('Winter', 2027), 'later'],
		['no announced season', unaired(null, null), 'tba'],
	])('%s', (_label, entry, expected) => {
		expect(mediaClass(entry, NOW)).toBe(expected);
	});

	it('only finished media can be played, whether or not it was rated', () => {
		expect(isAvailable(aired({ watch_status: 'completed' }), NOW)).toBe(true);
		expect(isAvailable(unaired('Winter', 2027), NOW)).toBe(false);
	});
});

describe('animeStatus — the case table', () => {
	// The table is shared with the backend: docs/features/readiness.md, "Where it is computed".
	const now = new Date(readinessCases.now);
	const cases = readinessCases.cases.map((c) => {
		const signals = {
			franchise_airing: c.franchise_airing ?? false,
			franchise_upcoming_key: c.franchise_upcoming ? seasonKey(c.franchise_upcoming[0] as string, c.franchise_upcoming[1] as number) : null,
		};
		const items = c.items.map((raw) => {
			const o = { ...readinessCases.defaults, ...raw };
			return item({
				airing_status: o.airing_status,
				watch_status: o.watch_status as WatchlistItem['watch_status'],
				relation_type: o.relation_type as WatchlistItem['relation_type'],
				anime_season_name: (o.season?.[0] ?? null) as WatchlistItem['anime_season_name'],
				anime_season_year: (o.season?.[1] ?? null) as number | null,
				total_watch_time: o.total_watch_time,
				...signals,
			});
		});
		return [c.label, items, c.expected] as const;
	});

	it.each(cases)('%s → %s', (_label, items, expected) => {
		expect(animeStatus([...items], now)).toBe(expected);
	});

	it('counts a standalone anime as ready', () => {
		const long = [aired({ franchise_airing: true, total_watch_time: STANDALONE_SECONDS })];
		expect(isReady(animeStatus(long, NOW))).toBe(true);
	});
});

describe('filterByReadiness', () => {
	const readyAnime = [
		aired({ anime_uuid: 'ready', watch_status: 'completed' }),
		aired({ anime_uuid: 'ready' }),
		unaired('Winter', 2028, { anime_uuid: 'ready' }),
	];
	const hotAnime = [aired({ anime_uuid: 'hot' }), airing({ anime_uuid: 'hot' })];
	const all = [...readyAnime, ...hotAnime];
	const statuses = statusByAnime(all, NOW);
	const uuids = (items: ReturnType<typeof item>[]) => [...new Set(items.map((i) => i.anime_uuid))];

	it('shows everything when no chip is selected', () => {
		expect(filterByReadiness(all, statuses, [], 'anime', NOW)).toHaveLength(all.length);
	});

	it('drops every entry of an anime outside the selection', () => {
		const kept = filterByReadiness(all, statuses, ['ready'], 'anime', NOW);
		expect(uuids(kept)).toEqual(['ready']);
		expect(kept).toHaveLength(3);
	});

	it('unions the chips, like the tag and priority filters', () => {
		expect(uuids(filterByReadiness(all, statuses, ['ready', 'hot'], 'anime', NOW)).sort()).toEqual([
			'hot',
			'ready',
		]);
	});

	it('admits a standalone anime under the Ready chip', () => {
		// Standalone is a flavour of ready, not a chip of its own.
		const long = [aired({ anime_uuid: 's', franchise_airing: true, total_watch_time: 61 * 3600 })];
		expect(animeStatus(long, NOW)).toBe('standalone');
		expect(filterByReadiness(long, statusByAnime(long, NOW), ['ready'], 'anime', NOW)).toHaveLength(1);
	});

	it('narrows a READY anime at media grain to what can be played, rewatches included', () => {
		const kept = filterByReadiness(all, statuses, ['ready'], 'media', NOW);
		// The 2028 entry drops (unplayable); the already-rated one stays (a rewatch).
		expect(kept).toHaveLength(2);
		expect(kept.every((i) => i.airing_status === 'Finished Airing')).toBe(true);
	});

	it('keeps every entry of a HOT anime at media grain, because there the airing one is the answer', () => {
		const kept = filterByReadiness(all, statuses, ['hot'], 'media', NOW);
		expect(kept).toHaveLength(2);
		expect(kept.some((i) => i.airing_status === 'Currently Airing')).toBe(true);
	});

	it('does not let a lone airing side story vanish on a grain toggle', () => {
		// The two grains must agree. A `ready` verdict here would show at anime grain
		// and vanish at media grain, because the media narrowing rejects `airing` —
		// same data, same chip, opposite answers. Blocking it is what aligns them, and
		// the narrowing never applies to a non-ready verdict, so `isAvailable` needs
		// no change.
		const lone = [airing({ anime_uuid: 'ova', relation_type: 'side_story' })];
		const verdict = statusByAnime(lone, NOW);
		expect(verdict.get('ova')).toBe('hot');
		for (const grain of ['anime', 'media'] as const) {
			expect(filterByReadiness(lone, verdict, ['ready'], grain, NOW)).toHaveLength(0);
			expect(filterByReadiness(lone, verdict, ['hot'], grain, NOW)).toHaveLength(1);
		}
	});

	it('drops an entry whose anime is missing from the map', () => {
		// No verdict is not a passing verdict — the chip filters it out rather than showing it.
		expect(filterByReadiness(all, new Map(), ['ready'], 'anime', NOW)).toHaveLength(0);
	});
});

describe('the verdict is scoped to the selected lists', () => {
	// `buildWatchlistView` hands `statusByAnime` the tag-filtered entries, so an anime can
	// read differently under two selections. These cover what that moves and what it does
	// not — through the real `filterByTags`, so they exercise the match production runs.
	const onList = (items: ReturnType<typeof item>[], tag: string) =>
		statusByAnime(filterByTags(items, [tag]), NOW).get('x');

	it('does not unblock a franchise whose airing season sits on another list', () => {
		// The hazard scoping had to clear. B1 narrows away here and B2 catches it instead,
		// so the verdict does not move — readiness.md B1/B2 for why the column still reports.
		const spread = [
			aired({ anime_uuid: 'x', tag_uuid: 'binge', franchise_airing: true }),
			airing({ anime_uuid: 'x', tag_uuid: 'ongoing', franchise_airing: true }),
		];
		expect(statusByAnime(spread, NOW).get('x')).toBe('hot');
		expect(onList(spread, 'binge')).toBe('hot');
	});

	it('releases a season you dropped once it is parked on another list', () => {
		// B1 has no dropped exemption, but `franchise_airing` does — so this is the one case
		// where B1 narrowing is observable, B2 having nothing left to block with. The second
		// escape hatch beside unlisting it.
		const bailed = [
			aired({ anime_uuid: 'x', tag_uuid: 'binge' }),
			airing({ anime_uuid: 'x', tag_uuid: 'gave-up', watch_status: 'dropped' }),
		];
		expect(statusByAnime(bailed, NOW).get('x')).toBe('hot');
		expect(onList(bailed, 'binge')).toBe('ready');
	});

	it('reads a list of finished seasons as a rewatch when the sequel is parked elsewhere', () => {
		// A is scoped too. Across the whole watchlist the announced sequel means "nothing new
		// to watch"; on the list you selected there is a finished season, and a rewatch is
		// watchable. The franchise key is set and genuinely far off, so B2 is not what allows
		// this — A narrowing is.
		const parked = [
			aired({
				anime_uuid: 'x',
				tag_uuid: 'done',
				watch_status: 'completed',
				franchise_upcoming_key: seasonKey('Winter', 2028),
			}),
			unaired('Winter', 2028, {
				anime_uuid: 'x',
				tag_uuid: 'later',
				franchise_upcoming_key: seasonKey('Winter', 2028),
			}),
		];
		expect(statusByAnime(parked, NOW).get('x')).toBe('waiting');
		expect(onList(parked, 'done')).toBe('ready');
	});
});
