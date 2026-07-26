import {
	episodesWatchedLabel,
	formatDuration,
	formatEpisodeCount,
	formatMediaType,
	formatSeason,
	formatSeasonRange,
	isSeasonRange,
	watchStatusLabel,
} from '$lib/utils/formatString';
import { MAIN_RELATIONS } from '$lib/utils/relations';
import type { AnimeDetail, AnimeMediaItem, MediaConnected, MediaDetail, RatingOut } from '$lib/types/api';

/** Everything a `ShareCard` needs beyond the title, score and ratings. */
export interface ShareCardContent {
	coverUrl: string | null;
	/** One entry per rendered line — the caller breaks them, not CSS. */
	metaLines: string[];
	statusLine: string | null;
}

/**
 * The catalog fields a media's meta line reads. A `Pick` rather than a hand-written shape,
 * so a backend-driven narrowing (say `media_type` becoming a union) is a compile error here
 * instead of being silently absorbed. `AnimeMediaItem` satisfies it structurally, which is
 * what lets a one-entry anime borrow the media wording.
 */
type MediaFacts = Pick<
	MediaConnected,
	'media_type' | 'anime_season_name' | 'anime_season_year' | 'episodes' | 'total_watch_time'
>;

/**
 * "TV · Fall 2020 · 9h 36m" — one media's catalog facts.
 *
 * Runtime is always the catalog's full length, never the part you watched: this line
 * describes the show, not your progress.
 */
function mediaMetaLine(media: MediaFacts, withEpisodes: boolean): string {
	const parts = [formatMediaType(media.media_type)];
	const season = formatSeason(media.anime_season_name, media.anime_season_year);
	if (season) parts.push(season);
	if (withEpisodes && media.episodes !== null) parts.push(formatEpisodeCount(media.episodes));
	if (media.total_watch_time !== null) parts.push(formatDuration(media.total_watch_time));
	return parts.join(' · ');
}

/**
 * The pair of lines describing one rated media.
 *
 * Built together because the episode count belongs on exactly one of them, and a single
 * predicate decides which: the status line takes it as watched-of-total whenever the rating
 * records a count, and only then does the catalog line drop it. So the count is never shown
 * twice, and never lost on a rating predating per-status episode counts.
 */
function singleMediaLines(media: MediaFacts, rating: RatingOut): Omit<ShareCardContent, 'coverUrl'> {
	const watched = rating.episodes_watched;

	const status = [watchStatusLabel(rating.watch_status)];
	if (watched !== null) status.push(episodesWatchedLabel(watched, media.episodes));
	if (rating.watched_count > 1) status.push(`watched ${rating.watched_count}×`);

	return {
		metaLines: [mediaMetaLine(media, watched === null)],
		statusLine: status.join(' · '),
	};
}

/** Card content for a single media's own rating. */
export function mediaShareContent(media: MediaDetail, rating: RatingOut): ShareCardContent {
	return { coverUrl: media.cover_image, ...singleMediaLines(media, rating) };
}

/**
 * Relation buckets for the franchise status line, in story order. Main = the canonical
 * chain plus retellings, the app-wide `MAIN_RELATIONS` spine. Labels are card copy, which
 * is why they live here rather than with the relation sets.
 */
const BUCKETS: { label: string; holds: (relationType: string) => boolean }[] = [
	{ label: 'main media', holds: (r) => MAIN_RELATIONS.has(r) },
	{ label: 'side media', holds: (r) => r === 'side_story' },
	{ label: 'recaps', holds: (r) => r === 'summary' },
];

/** "3/5 main media · 1/2 side media" — a bucket the anime has no media in is omitted, so a
 *  franchise without recaps doesn't advertise "0/0 recaps". */
function franchiseStatusLine(media: AnimeMediaItem[], ratings: RatingOut[]): string | null {
	const rated = new Set(ratings.map((r) => r.media_uuid));
	const line = BUCKETS.map(({ label, holds }) => {
		const inBucket = media.filter((m) => holds(m.relation_type));
		if (inBucket.length === 0) return null;
		return `${inBucket.filter((m) => rated.has(m.uuid)).length}/${inBucket.length} ${label}`;
	})
		.filter(Boolean)
		.join(' · ');
	return line || null;
}

/**
 * Card content for an anime.
 *
 * Not-yet-aired entries are excluded from everything the card says: they can't be rated, so
 * counting an announced sequel would make a fully-watched franchise read as unfinished.
 *
 * An anime that is really one entry (a film, a single-season show) borrows the media
 * wording — its own type and runtime say more than "1/1 main media" ever could. "One entry"
 * is measured over the *aired* set, so an announced sequel can't flip a film into the
 * franchise shape. The shape is chosen once here, so the cover and the text can't disagree
 * about which one is in play.
 */
export function animeShareContent(anime: AnimeDetail, ratings: RatingOut[]): ShareCardContent {
	const aired = anime.media.filter((m) => m.airing_status !== 'Not yet aired');

	const sole = aired.length === 1 ? aired[0] : null;
	const soleRating = sole ? ratings.find((r) => r.media_uuid === sole.uuid) : undefined;
	if (sole && soleRating) {
		return {
			coverUrl: sole.cover_image ?? anime.cover_image,
			...singleMediaLines(sole, soleRating),
		};
	}

	const season = formatSeasonRange(anime.season_start, anime.season_end);
	const runtime = anime.total_watch_time !== null ? formatDuration(anime.total_watch_time) : null;
	const episodes = anime.total_episodes !== null ? formatEpisodeCount(anime.total_episodes) : null;
	const lengthLine = [episodes, runtime].filter(Boolean).join(' · ');

	// A season RANGE plus the length facts overflows one line, so it gets its own.
	const metaLines = isSeasonRange(anime.season_start, anime.season_end)
		? [season, lengthLine]
		: [[season, lengthLine].filter(Boolean).join(' · ')];

	return {
		coverUrl: anime.cover_image,
		metaLines: metaLines.filter((l): l is string => !!l),
		statusLine: franchiseStatusLine(aired, ratings),
	};
}
