import {
	cleanDescription,
	episodesWatchedLabel,
	formatAiringStatus,
	formatDuration,
	formatEpisodeCount,
	formatMediaType,
	formatSeason,
	formatSeasonRange,
	isSeasonRange,
	watchStatusLabel,
} from '$lib/utils/formatString';
import { meanScore } from '$lib/utils/ratingStats';
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
 * Stands in for a fact the catalog doesn't have.
 *
 * The info card never drops a missing fact the way the page does. An image travels without
 * the app around it, so "no studio on record" and "we forgot to render the studio" have to
 * be distinguishable — the same reasoning that already makes the rating card show greyed
 * `--` attribute pills where the page hides the section outright.
 */
const MISSING = '--';

/** Chip caps. The card is a fixed 540×675 with no scroll container, so these are what keep
 *  a heavily-tagged anime from pushing the synopsis out of frame. */
const SHARE_MAX_GENRES = 6;
const SHARE_MAX_STUDIOS = 2;
/**
 * Synopsis budget — the ~12 lines the card's tightest layout has room for, at ~65
 * characters a line.
 *
 * Belt and braces with the card's own `line-clamp`, and the two guard different failures:
 * the clamp puts an ellipsis on text that fits the box but not the line count, while this
 * bounds the string itself. `-webkit-line-clamp` is a prefixed legacy property the
 * rasterizer's foreignObject pass isn't guaranteed to carry across, and a dropped
 * `-webkit-box-orient` reflows the box to a SINGLE line — so the cap is what keeps that
 * failure to a slightly-short synopsis rather than a one-line one.
 */
export const SHARE_SYNOPSIS_MAX_CHARS = 820;

export type ShareBadgeTone = 'airing' | 'unaired' | 'upcoming' | 'finished' | 'complete';
/** A pill under the card's title — the hero's airing state, carried into the image. */
export interface ShareBadge {
	label: string;
	tone: ShareBadgeTone;
}

/** Which of the two cards a title can produce. */
export type ShareVariant = 'rating' | 'info';

/**
 * The half of the card below the hero row, and what sits at the foot of the hero column.
 * A discriminated union, so the fields of the variant you aren't rendering are not merely
 * unused — they're absent.
 */
export type ShareCardBody =
	| {
			kind: 'rating';
			/** Never null — this variant only exists when there is a rating to show. */
			score: number;
			ratingStep: number;
			/** Watch context beside the score, e.g. "Completed · watched 2×" or the anime
			 *  grain's rated-per-relation breakdown. */
			statusLine: string | null;
			/** N ratings at anime grain, exactly one at media grain — feeds radar + pills. */
			ratings: RatingOut[];
	  }
	| {
			kind: 'info';
			/** Already capped; a trailing "+N" absorbs the remainder. `['--']` when none. */
			genres: string[];
			/** "16+", or `--`. Never null — see MISSING. */
			ageRating: string;
			studios: string[];
			synopsis: string | null;
	  };

/**
 * One fully-assembled card. Built here rather than in the two grain wrappers so the anime
 * and media sides can't drift — the documented reason those wrappers exist at all.
 */
export interface ShareVariantContent {
	/** Top-right of the brand header — what this card is. */
	headerLabel: string;
	coverUrl: string | null;
	metaLines: string[];
	badges?: ShareBadge[];
	body: ShareCardBody;
}

/** Header label for the info card. Deliberately a call to action, since the case it exists
 *  for is recommending something you haven't watched. */
const INFO_LABEL = 'Check this out';
/** Header label for the rating card. Exported because the dialog's variant toggle labels
 *  itself from the same string. */
export const RATING_LABEL = 'My rating';

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
 * Where the episode count goes on a media's meta line.
 *
 * `omit` — the status line is carrying it as watched-of-total (rating variant).
 * `show` — include it, drop it silently when the catalog has no count.
 * `require` — include it either way, as `-- eps` when unknown (info variant, which never
 *   drops a fact; see MISSING).
 */
type EpisodeMode = 'omit' | 'show' | 'require';

/**
 * "TV · Fall 2020 · 9h 36m" — one media's catalog facts.
 *
 * Runtime is always the catalog's full length, never the part you watched: this line
 * describes the show, not your progress.
 */
function mediaMetaLine(media: MediaFacts, mode: EpisodeMode): string {
	const parts = [formatMediaType(media.media_type)];
	const season = formatSeason(media.anime_season_name, media.anime_season_year);
	if (season) parts.push(season);
	const count = episodeLabel(media.episodes, mode);
	if (count) parts.push(count);
	if (media.total_watch_time !== null) parts.push(formatDuration(media.total_watch_time));
	return parts.join(' · ');
}

function episodeLabel(episodes: number | null, mode: EpisodeMode): string | null {
	if (mode === 'omit') return null;
	if (episodes !== null) return formatEpisodeCount(episodes);
	return mode === 'require' ? `${MISSING} eps` : null;
}

/**
 * The airing state as card pills — the hero's four-way cascade plus story-complete.
 *
 * One function for both grains: `formatAiringStatus(x, false)` is the identity for every
 * status, so the media grain (which has neither `has_upcoming` nor a completion flag) just
 * passes false/false and gets its raw status back with no special case.
 */
function statusBadges(
	airingStatus: string,
	hasUpcoming: boolean,
	isFinished: boolean,
): ShareBadge[] {
	const label = formatAiringStatus(airingStatus, hasUpcoming);
	let tone: ShareBadgeTone;
	if (airingStatus === 'Currently Airing') tone = 'airing';
	else if (airingStatus === 'Not yet aired') tone = 'unaired';
	else if (hasUpcoming) tone = 'upcoming';
	else tone = 'finished';

	const badges: ShareBadge[] = [{ label, tone }];
	if (isFinished) badges.push({ label: 'Story Complete', tone: 'complete' });
	return badges;
}

/** "16+", or `--` — the info card never drops a fact. */
function ageRatingLabel(numeric: number | null): string {
	return numeric !== null ? `${numeric}+` : MISSING;
}

/** Cap a chip list at `max`, absorbing the remainder into a trailing "+N". An empty list
 *  becomes a single `--` chip rather than vanishing. */
function shareChips(values: string[], max: number): string[] {
	if (values.length === 0) return [MISSING];
	if (values.length <= max) return [...values];
	return [...values.slice(0, max), `+${values.length - max}`];
}

/**
 * The synopsis, cleaned and cut to the card's budget on a word boundary.
 *
 * The boundary search gives up below 60% of the cap, which is what keeps a CJK synopsis
 * (no spaces to break on) from being cut to a fraction of its allowance.
 */
export function shareSynopsis(description: string | null): string | null {
	if (!description) return null;
	const clean = cleanDescription(description);
	if (!clean) return null;
	if (clean.length <= SHARE_SYNOPSIS_MAX_CHARS) return clean;

	const cut = clean.slice(0, SHARE_SYNOPSIS_MAX_CHARS);
	const lastSpace = cut.lastIndexOf(' ');
	const body = lastSpace > SHARE_SYNOPSIS_MAX_CHARS * 0.6 ? cut.slice(0, lastSpace) : cut;
	return `${body.replace(/[\s.,;:—–-]+$/, '')}…`;
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
		metaLines: [mediaMetaLine(media, watched === null ? 'show' : 'omit')],
		statusLine: status.join(' · '),
	};
}

/** Card content for a single media's own rating. */
export function mediaShareContent(media: MediaDetail, rating: RatingOut): ShareCardContent {
	return { coverUrl: media.cover_image, ...singleMediaLines(media, rating) };
}

/** The rating card for one media. */
export function mediaRatingCard(
	media: MediaDetail,
	rating: RatingOut,
	ratingStep: number,
): ShareVariantContent {
	const { coverUrl, metaLines, statusLine } = mediaShareContent(media, rating);
	return {
		headerLabel: RATING_LABEL,
		coverUrl,
		metaLines,
		body: { kind: 'rating', score: rating.rating, ratingStep, statusLine, ratings: [rating] },
	};
}

/** The info card for one media — no rating anywhere in it. */
export function mediaInfoCard(media: MediaDetail): ShareVariantContent {
	return {
		headerLabel: INFO_LABEL,
		coverUrl: media.cover_image,
		// With no status line to carry it, the episode count comes up here.
		metaLines: [mediaMetaLine(media, 'require')],
		badges: statusBadges(media.airing_status, false, false),
		body: {
			kind: 'info',
			genres: shareChips(media.genres, SHARE_MAX_GENRES),
			ageRating: ageRatingLabel(media.age_rating_numeric),
			studios: shareChips(media.studio, SHARE_MAX_STUDIOS),
			synopsis: shareSynopsis(media.description),
		},
	};
}

/**
 * Relation buckets for the franchise status line, in story order. Main = the canonical
 * chain plus retellings, the app-wide `MAIN_RELATIONS` spine. Labels are card copy, which
 * is why they live here rather than with the relation sets.
 */
const BUCKETS: { one: string; many: string; holds: (relationType: string) => boolean }[] = [
	{ one: 'main media', many: 'main media', holds: (r) => MAIN_RELATIONS.has(r) },
	{ one: 'side media', many: 'side media', holds: (r) => r === 'side_story' },
	{ one: 'recap', many: 'recaps', holds: (r) => r === 'summary' },
];

/**
 * "3/5 main media · 1/2 side media", or "5 main media · 2 side media" with no `ratings`.
 *
 * One function for both, so the omit-an-empty-bucket rule can't drift: a franchise without
 * recaps must never advertise "0/0 recaps" on either variant. Pass `null` for the info
 * variant, where there is no progress to report — only the shape of the franchise.
 */
function franchiseBucketLine(media: AnimeMediaItem[], ratings: RatingOut[] | null): string | null {
	const rated = ratings && new Set(ratings.map((r) => r.media_uuid));
	const line = BUCKETS.map(({ one, many, holds }) => {
		const inBucket = media.filter((m) => holds(m.relation_type));
		if (inBucket.length === 0) return null;
		// Singularize on the DISPLAYED total, so the rating variant reads "1/1 recap" too.
		const label = inBucket.length === 1 ? one : many;
		if (!rated) return `${inBucket.length} ${label}`;
		return `${inBucket.filter((m) => rated.has(m.uuid)).length}/${inBucket.length} ${label}`;
	})
		.filter(Boolean)
		.join(' · ');
	return line || null;
}

/**
 * The season + length lines for a whole anime. A season RANGE plus the length facts
 * overflows one line, so it gets its own.
 */
function animeLengthLines(anime: AnimeDetail, episodes: EpisodeMode): string[] {
	const season = formatSeasonRange(anime.season_start, anime.season_end);
	const runtime = anime.total_watch_time !== null ? formatDuration(anime.total_watch_time) : null;
	const lengthLine = [episodeLabel(anime.total_episodes, episodes), runtime].filter(Boolean).join(' · ');

	const lines = isSeasonRange(anime.season_start, anime.season_end)
		? [season, lengthLine]
		: [[season, lengthLine].filter(Boolean).join(' · ')];
	return lines.filter((l): l is string => !!l);
}

/**
 * The single aired entry, when an anime really is just one — a film, a single-season show.
 * Measured over the *aired* set so an announced sequel can't flip a film into the franchise
 * shape; not-yet-aired entries can't be rated and shouldn't be counted.
 */
function soleAiredEntry(aired: AnimeMediaItem[]): AnimeMediaItem | null {
	return aired.length === 1 ? aired[0] : null;
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
	const aired = airedMedia(anime);

	const sole = soleAiredEntry(aired);
	const soleRating = sole ? ratings.find((r) => r.media_uuid === sole.uuid) : undefined;
	if (sole && soleRating) {
		return {
			coverUrl: sole.cover_image ?? anime.cover_image,
			...singleMediaLines(sole, soleRating),
		};
	}

	return {
		coverUrl: anime.cover_image,
		metaLines: animeLengthLines(anime, 'show'),
		statusLine: franchiseBucketLine(aired, ratings),
	};
}

function airedMedia(anime: AnimeDetail): AnimeMediaItem[] {
	return anime.media.filter((m) => m.airing_status !== 'Not yet aired');
}

/**
 * Info content for a whole anime.
 *
 * Shares `animeShareContent`'s two shape rules verbatim — aired-only, and a one-entry anime
 * borrowing the media wording — so the two variants of the same anime describe it the same
 * way. The difference is only that the borrow no longer needs a rating to trigger, and that
 * the franchise breakdown moves from the status line up into the meta lines, as a plain
 * count of what the franchise contains rather than how much of it you've seen.
 */
export function animeInfoCard(anime: AnimeDetail): ShareVariantContent {
	const aired = airedMedia(anime);
	const sole = soleAiredEntry(aired);

	const metaLines = sole
		? [mediaMetaLine(sole, 'require')]
		: [...animeLengthLines(anime, 'require'), franchiseBucketLine(aired, null)].filter(
				(l): l is string => !!l,
			);

	return {
		headerLabel: INFO_LABEL,
		coverUrl: sole ? (sole.cover_image ?? anime.cover_image) : anime.cover_image,
		metaLines,
		badges: statusBadges(anime.airing_status, anime.has_upcoming, anime.is_finished),
		body: {
			kind: 'info',
			genres: shareChips(anime.genres, SHARE_MAX_GENRES),
			ageRating: ageRatingLabel(anime.age_rating_numeric),
			studios: shareChips(anime.studios, SHARE_MAX_STUDIOS),
			synopsis: shareSynopsis(anime.description),
		},
	};
}

/** The rating card for a whole anime — its headline score is the plain mean of the media
 *  you've rated, the same number `RatingsOverview` shows on the page. */
export function animeRatingCard(
	anime: AnimeDetail,
	ratings: RatingOut[],
	ratingStep: number,
): ShareVariantContent {
	const { coverUrl, metaLines, statusLine } = animeShareContent(anime, ratings);
	return {
		headerLabel: 'My rating',
		coverUrl,
		metaLines,
		body: { kind: 'rating', score: meanScore(ratings), ratingStep, statusLine, ratings },
	};
}
