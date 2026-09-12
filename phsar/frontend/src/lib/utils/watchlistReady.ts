// "Can I actually start this tonight?" — the rules behind the watchlist's Ready filter.
//
// A watchlist mixes two things: entries you can start now, and entries parked for the
// future. Separating them takes two questions, and both are per-user, because both read
// which media you watchlisted and what you have rated. See docs/features/readiness.md
// for the full case table; this file is the executable form of it.
import { MAIN_RELATIONS } from '$lib/utils/relations';
import { nextSeasonKey, seasonKey } from '$lib/utils/getSeason';
import type { WatchlistItem } from '$lib/types/api';

/** Where a media sits relative to now. Only `airing` and `soon` force a wait; only
 *  `aired` can be watched. `later` and `tba` are far enough out to be irrelevant to
 *  what you start tonight, which is why they are distinct from `soon`. */
export type MediaClass = 'aired' | 'airing' | 'soon' | 'later' | 'tba';

/** The anime-grain verdict. `ready` and `standalone` both pass the filter; they differ
 *  only in what the card says, because "ready even though the franchise is ongoing" is
 *  worth surfacing. */
export type ReadyStatus = 'ready' | 'standalone' | 'hot' | 'waiting';

/** A single watchlisted media long enough to stand on its own, so ongoing franchise
 *  content you did NOT list stops blocking it — Dragon Ball without Super, Naruto
 *  without Boruto, Gintama.
 *
 *  Applied **per media, never summed**: a franchise told in short seasons must not sum
 *  its way past the line, or a new season gets hidden from someone who wants it. The
 *  value is calibrated against the catalogue, so re-measure before moving it — the
 *  feature doc carries the study.
 *
 *  Open-ended shows have no episode count, so `total_watch_time` is null and they never
 *  clear this. Harmless — they are airing, so they are blocked anyway. */
export const STANDALONE_SECONDS = 20 * 3600;

const AIRED = 'Finished Airing';
const AIRING = 'Currently Airing';

/** Where one watchlisted media sits relative to `now`.
 *
 *  Derived from the season, never from `aired_from`: a padded date claims a day-precision
 *  premiere it does not have. */
export function mediaClass(item: WatchlistItem, now: Date = new Date()): MediaClass {
	if (item.airing_status === AIRED) return 'aired';
	if (item.airing_status === AIRING) return 'airing';
	const key = seasonKey(item.anime_season_name, item.anime_season_year);
	if (key === null) return 'tba';
	// `<=`, not `===`: a title still marked unaired whose season has already started is
	// a scrape that hasn't caught up. Treating it as imminent is the safe read.
	return key <= nextSeasonKey(now) ? 'soon' : 'later';
}

/** True when this media can be played right now — the media-grain filter, and the
 *  "something to watch" half of the anime verdict. Rated media count: a finished entry
 *  you have already rated is a rewatch, and a rewatch is watchable. */
export function isAvailable(item: WatchlistItem, now: Date = new Date()): boolean {
	return mediaClass(item, now) === 'aired';
}

/**
 * The verdict for one anime, given every watchlist entry belonging to it. Three tests,
 * all of which must pass — the case table and the exemptions are in the feature doc:
 *
 * - **A** — is there something to watch?
 * - **B1** — nothing you listed is airing or imminent.
 * - **B2** — nothing in the wider franchise is, including media you never listed.
 */
export function animeStatus(items: WatchlistItem[], now: Date = new Date()): ReadyStatus {
	// Classified once, carried with the entry. A parallel array indexed by callback
	// position would break silently the moment either side is reordered or filtered.
	const media = items.map((item) => ({ item, cls: mediaClass(item, now) }));

	const waitingOnUnaired = media.some(({ cls }) => cls === 'soon' || cls === 'later' || cls === 'tba');
	const hasFreshContent = media.some(
		({ item, cls }) => cls === 'aired' && item.watch_status !== 'completed',
	);
	const somethingToWatch = !waitingOnUnaired || hasFreshContent;

	// Only the main story can park a franchise — an upcoming OVA, movie or recap is not
	// a season you wait for. (The franchise columns are filtered the same way in SQL.)
	const nothingListedPending = !media.some(
		({ item, cls }) =>
			MAIN_RELATIONS.has(item.relation_type) && (cls === 'airing' || cls === 'soon'),
	);

	// Per-anime, so identical on every entry; an empty list never reaches here.
	const { franchise_airing, franchise_upcoming_key } = items[0];
	const franchiseBlocks =
		franchise_airing ||
		(franchise_upcoming_key !== null && franchise_upcoming_key <= nextSeasonKey(now));
	const standalone =
		franchiseBlocks && items.some((i) => (i.total_watch_time ?? 0) >= STANDALONE_SECONDS);

	if (!nothingListedPending || (franchiseBlocks && !standalone)) return 'hot';
	if (!somethingToWatch) return 'waiting';
	// Ready, but the franchise is ongoing and only the length of what you listed
	// rescued it — worth saying on the card, since it is the surprising verdict.
	return standalone ? 'standalone' : 'ready';
}

/**
 * Every anime's verdict, keyed by `anime_uuid`.
 *
 * Build it from the UNFILTERED entry set and pass it down — that is what makes the
 * verdict independent of the list and priority chips. Computing it per filtered view
 * instead would let parking an airing season on a separate list silently unblock the
 * franchise, and the same anime would flip verdict as chips toggle.
 */
export function statusByAnime(
	items: WatchlistItem[],
	now: Date = new Date(),
): Map<string, ReadyStatus> {
	const verdicts = new Map<string, ReadyStatus>();
	for (const [uuid, group] of Map.groupBy(items, (i) => i.anime_uuid)) {
		verdicts.set(uuid, animeStatus(group, now));
	}
	return verdicts;
}

/** The filter chips. Derived from `ReadyStatus` so a new verdict is a compile error here
 *  until it is given a chip. Labels and wording live in `utils/watchlist.READY_FILTERS`. */
export type ReadyFilterKey = Exclude<ReadyStatus, 'standalone'>;

/** Which chip each verdict answers to. The `standalone → ready` row is the whole reason
 *  this table exists rather than an identity mapping — it is where "standalone still
 *  counts as watchable" is written down, once. */
const CHIP_OF: Record<ReadyStatus, ReadyFilterKey> = {
	ready: 'ready',
	standalone: 'ready',
	hot: 'hot',
	waiting: 'waiting',
};

/** Is this verdict watchable? */
export function isReady(status: ReadyStatus): boolean {
	return CHIP_OF[status] === 'ready';
}

/** Does this verdict fall under any of the selected chips? Empty selection = all, the
 *  same union convention as the list and priority chips. */
export function matchesFilter(status: ReadyStatus, selected: ReadyFilterKey[]): boolean {
	return selected.length === 0 || selected.includes(CHIP_OF[status]);
}

