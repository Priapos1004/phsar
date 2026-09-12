/** Canonical within-year ordering of anime seasons (Winter → Fall). Mirrors the
 * backend `models/media.SEASON_ORDER`; the single frontend source so the spoiler
 * frontier, the ratings season filter, and any future season sort can't disagree on
 * order. The 1-based offset is load-bearing for `seasonKey` below. */
export const SEASON_ORDER: Record<string, number> = {
	Winter: 1,
	Spring: 2,
	Summer: 3,
	Fall: 4,
};

/** A season as one sortable integer, `year * 10 + rank`, so two seasons compare with
 *  `<`. Null when the season is unknown — an anime with no announced season sorts
 *  nowhere rather than at the start of its year.
 *
 *  The same encoding the backend's `watchlist_dao._SEASON_KEY` emits for
 *  `franchise_upcoming_key`, which is the only reason it is an integer at all. No
 *  import can span the two languages, so each side pins the encoding in its own test
 *  against the same season. */
export function seasonKey(name: string | null, year: number | null): number | null {
	const rank = name ? SEASON_ORDER[name] : undefined;
	return rank && year ? year * 10 + rank : null;
}

/** `seasonKey` of the season after the current one — the boundary "is this airing too
 *  soon to start the franchise now?" is measured against. Fall rolls into next Winter.
 *
 *  `now` is injectable because the answer changes on a calendar boundary no test can
 *  otherwise reach. */
export function nextSeasonKey(now: Date = new Date()): number {
	const next = SEASON_ORDER[currentSeasonName(now)] % SEASONS.length; // Fall (4) wraps to 0
	return seasonKey(SEASONS[next], now.getFullYear() + (next === 0 ? 1 : 0))!;
}

const SEASONS = ['Winter', 'Spring', 'Summer', 'Fall'];

/** The current season's name. Quarters, matching the backend's `_month_to_season`. */
function currentSeasonName(now: Date): string {
	return SEASONS[Math.floor(now.getMonth() / 3)];
}

export function getCurrentSeason(now: Date = new Date()): string {
	return `${currentSeasonName(now)} ${now.getFullYear()}`;
}
