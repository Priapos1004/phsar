import { RELATION_TYPE_LABELS } from '$lib/utils/chartColors';
import type { JobKind } from '$lib/types/api';

/** Labels for the numeric age-rating buckets (mirrors the backend AGE_RATING_MAP:
 * G=0, PG=6, PG-13=13, R=17, R+=18). */
export const AGE_RATING_LABELS: Record<number, string> = {
	0: 'All Ages',
	6: 'PG',
	13: 'PG-13',
	17: 'R-17+',
	18: 'R+',
};

/** Formats a raw relation_type value to a user-friendly label. */
export function formatRelationType(type: string): string {
	return RELATION_TYPE_LABELS[type] ?? type;
}

/** Escape a string for safe interpolation into an HTML string. ECharts renders a
 * tooltip `formatter`'s return value as HTML (`innerHTML`), so any catalog-sourced
 * text spliced into one — anime/media titles, genre/studio names — must be escaped,
 * since Svelte's auto-escaping doesn't reach inside these hand-built strings. */
export function escapeHtml(s: string): string {
	return s
		.replace(/&/g, '&amp;')
		.replace(/</g, '&lt;')
		.replace(/>/g, '&gt;')
		.replace(/"/g, '&quot;')
		.replace(/'/g, '&#39;');
}

const MEDIA_TYPE_LABELS: Record<string, string> = {
	TVSpecial: 'TV Special',
};

/** Formats a raw media_type value to a user-friendly label. */
export function formatMediaType(type: string): string {
	return MEDIA_TYPE_LABELS[type] ?? type;
}

export const JOB_KIND_LABELS: Record<JobKind, string> = {
	user_scrape: 'User scrape',
	update_sweep: 'Update sweep',
	seasonal_sweep: 'Seasonal sweep',
	backup: 'Backup',
	restore: 'Restore',
};

/** Today only seasonal_sweep enqueues parented system children; a future
 * kind doing the same joins this set and the Jobs Log expander Just Works.
 * Backend allows `?parent_uuid=` for any kind — this is purely the
 * frontend's "row deserves a chevron" guard. */
export const PARENTING_KINDS: ReadonlySet<JobKind> = new Set<JobKind>(['seasonal_sweep']);

/** Where a *succeeded* job of each kind navigates when its bell row is clicked.
 * Per-kind static metadata (kept here next to JOB_KIND_LABELS rather than as an
 * if-ladder in JobBell); a kind absent from the map has no clickable target. */
export const JOB_SUCCESS_HREF: Partial<Record<JobKind, string>> = {
	user_scrape: '/library/add',
	backup: '/admin?tab=backups',
};

/** Formats a JobKind enum value to a user-friendly label. Accepts string
 * so callers can pass raw backend values without a guard; unknown values
 * fall through unchanged. */
export function formatJobKind(kind: JobKind | string): string {
	return JOB_KIND_LABELS[kind as JobKind] ?? kind;
}

/**
 * Format a number with commas for thousands, while preserving decimals.
 * Examples:
 *  1234242    -> "1,234,242"
 *  1234.12    -> "1,234.12"
 */
export function formatNumber(value: number | string): string {
	const [intPart, decimalPart] = value.toString().split('.');
	const formattedInt = Number(intPart).toLocaleString('en-US');
	return decimalPart ? `${formattedInt}.${decimalPart}` : formattedInt;
}

/**
 * Convert seconds into a readable duration string: "1d 4h 12m 33s"
 */
export function formatDuration(seconds: number): string {
	if (seconds <= 0) return '0s';

	const days = Math.floor(seconds / (3600 * 24));
	const hours = Math.floor((seconds % (3600 * 24)) / 3600);
	const minutes = Math.floor((seconds % 3600) / 60);
	const secs = seconds % 60;

	const parts = [];
	if (days) parts.push(`${days}d`);
	if (hours) parts.push(`${hours}h`);
	if (minutes) parts.push(`${minutes}m`);
	if (secs || parts.length === 0) parts.push(`${secs}s`);

	return parts.join(' ');
}

/**
 * Compact duration for tight spaces (e.g. axis ticks): the most-significant non-zero
 * unit plus up to `maxUnits-1` following units, with trailing zero units trimmed.
 * Unlike formatDuration it takes a CONTIGUOUS run of units rather than skipping zero
 * ones, so e.g. 1d 0h 1m reads "1d" (not a misleading "1d 1m") and adjacent ticks stay
 * on a consistent scale.
 */
export function formatDurationCompact(seconds: number, maxUnits = 2): string {
	if (seconds <= 0) return '0s';
	const units: [number, string][] = [
		[Math.floor(seconds / 86400), 'd'],
		[Math.floor((seconds % 86400) / 3600), 'h'],
		[Math.floor((seconds % 3600) / 60), 'm'],
		[Math.floor(seconds % 60), 's'],
	];
	const first = units.findIndex(([v]) => v > 0);
	if (first === -1) return '0s';
	const parts = units.slice(first, first + maxUnits);
	while (parts.length > 1 && parts[parts.length - 1][0] === 0) parts.pop();
	return parts.map(([v, u]) => `${v}${u}`).join(' ');
}

/**
 * Wall-clock duration between started_at and finished_at, or
 * started_at → `now` if the job is still running. Returns '—' for
 * never-started rows so callers don't need their own null guard.
 */
export function formatJobDuration(
	started_at: string | null, finished_at: string | null, now: number,
): string {
	if (!started_at) return '—';
	const start = new Date(started_at).getTime();
	const end = finished_at ? new Date(finished_at).getTime() : now;
	return formatDuration(Math.max(0, Math.floor((end - start) / 1000)));
}

/**
 * Subset of update_sweep `dynamic` fields that churn nightly on
 * popular anime — split out from the rest of the dynamic bucket on
 * the admin detail page so vote-count noise doesn't drown the
 * genuinely-interesting volatile fields (episodes, airing_status,
 * aired_to). Single source of truth so MediaChangeCard's tone
 * classifier and the page's filter chip stay in sync.
 */
const RATING_FIELD_NAMES = new Set(['score', 'scored_by']);

export function isRatingField(field: string): boolean {
	return RATING_FIELD_NAMES.has(field);
}

/**
 * Share of `value` over `total` as a percentage (0–100). Returns 0
 * when `total` is 0. Callers that need to distinguish "no data" from
 * "0%" should gate on `total > 0` themselves before calling — the
 * helper deliberately doesn't conflate the two via a nullable return.
 */
export function percentOf(value: number, total: number): number {
	return total > 0 ? (value / total) * 100 : 0;
}

/**
 * Format anime season name and year into a display string.
 * Returns null if either part is missing.
 */
export function formatSeason(name: string | null, year: number | null): string | null {
	if (name && year) return `${name} ${year}`;
	return null;
}

/**
 * Format a season range string from start and end seasons.
 * Returns the single season if they are the same or end is null.
 */
export function formatSeasonRange(start: string | null, end: string | null): string | null {
	if (!start) return null;
	if (!end) return start;
	return `${start} - ${end}`;
}

/**
 * Format an airing status string, appending "+ upcoming" when applicable.
 */
export function formatAiringStatus(status: string, hasUpcoming: boolean): string {
	if (status === 'Not yet aired') return status;
	if (status === 'Finished Airing') return hasUpcoming ? 'upcoming content' : status;
	return hasUpcoming ? `${status} + upcoming content` : status;
}

/**
 * Strip MAL attribution tags from description text:
 *   - "[Written by MAL Rewrite]"
 *   - trailing "(Source: ANN)" / "[Source: Wikipedia]" / etc.
 */
export function cleanDescription(text: string): string {
	return text
		.replace(/\s*\[Written by MAL Rewrite\]\s*/g, '')
		.replace(/\s*[\(\[]\s*Source\s*:[^\)\]]*[\)\]]\s*$/i, '')
		.trim();
}

export function formatShortDate(iso: string): string {
	return new Date(iso).toLocaleDateString('en-US', {
		month: 'short',
		day: 'numeric',
		year: 'numeric',
	});
}

export function formatShortDateTime(iso: string): string {
	return new Date(iso).toLocaleString('en-US', {
		month: 'short',
		day: 'numeric',
		year: 'numeric',
		hour: '2-digit',
		minute: '2-digit',
	});
}

export function formatBytes(bytes: number): string {
	if (bytes < 1024) return `${bytes} B`;
	if (bytes < 1024 * 1024) return `${(bytes / 1024).toFixed(1)} KB`;
	if (bytes < 1024 * 1024 * 1024) return `${(bytes / (1024 * 1024)).toFixed(1)} MB`;
	return `${(bytes / (1024 * 1024 * 1024)).toFixed(2)} GB`;
}

/**
 * Clamp a score to [0, 10] and round to the nearest step.
 * Examples (step=0.5): 6.6 -> 6.5, 9.656 -> 9.5, -1 -> 0, 15 -> 10, 7.25 -> 7.5
 * Examples (step=1):   6.6 -> 7, 9.3 -> 9, 0.4 -> 0
 */
export function clampAndSnapScore(val: number, step: number): number {
	const clamped = Math.min(10, Math.max(0, val));
	// Round to 2 dp (the finest rating step is 0.01) so step-division noise like
	// 535 * 0.01 = 5.3500000000000005 never reaches a saved rating in the first place.
	return roundScore(Math.round(clamped / step) * step);
}

/**
 * Number of decimal places in a number.
 * Examples: 0.5 -> 1, 0.25 -> 2, 0.1 -> 1, 0.01 -> 2, 1 -> 0, 6.25 -> 2
 */
export function decimalPlaces(value: number): number {
	const str = value.toString();
	const dot = str.indexOf('.');
	return dot === -1 ? 0 : str.length - dot - 1;
}

/**
 * Format a number to have a fixed number of digits after the decimal point.
 * Pads with trailing zeros or rounds as needed.
 *
 * Examples:
 *  formatDecimalDigits(5, 2)        -> "5.00"
 *  formatDecimalDigits(3.14159, 2)  -> "3.14"
 *  formatDecimalDigits(7.8, 4)      -> "7.8000"
 */
export function formatDecimalDigits(value: number, digits: number): string {
	return value.toFixed(digits);
}

/**
 * Round a 0–10 rating to the finest rating step (0.01 → 2 dp), shedding float-arithmetic
 * noise like 535 * 0.01 = 5.3500000000000005. The single guard behind both formatScore and
 * any value-derived decimal count — measure precision off `decimalPlaces(roundScore(r))`, never
 * the raw stored float, or one noisy legacy rating reports 16 decimals and blows out the display.
 */
export function roundScore(value: number): number {
	return Math.round(value * 100) / 100;
}

/**
 * Format a 0–10 rating for display. Rounds to the finest rating step (0.01 → 2 dp)
 * first to shed float-arithmetic noise (7.890000000000001 → "7.89"), then shows only
 * the decimals that remain so whole/half scores stay clean (8.5 → "8.5", 10 → "10").
 */
export function formatScore(value: number): string {
	const rounded = roundScore(value);
	return formatDecimalDigits(rounded, decimalPlaces(rounded));
}

/**
 * Resolve the display title based on user's name language preference.
 * Falls back through: preferred language → english name → romaji title.
 */
export function resolveTitle(
	title: string,
	nameEng: string | null | undefined,
	nameJap: string | null | undefined,
	language: 'english' | 'japanese' | 'romaji'
): string {
	if (language === 'japanese' && nameJap) return nameJap;
	if (language === 'english' && nameEng) return nameEng;
	// Fallback: romaji title (always present) is the universal fallback
	return title;
}

/**
 * Get subtitle titles for the hero card — the names NOT used as the main heading.
 * Returns up to 2 subtitle strings, skipping duplicates and the main title.
 */
export function resolveSubtitles(
	title: string,
	nameEng: string | null | undefined,
	nameJap: string | null | undefined,
	language: 'english' | 'japanese' | 'romaji'
): string[] {
	const main = resolveTitle(title, nameEng, nameJap, language);
	const candidates: string[] = [];

	// Add the other two name variants (not the selected language)
	if (language !== 'english' && nameEng && nameEng !== main) candidates.push(nameEng);
	if (language !== 'romaji' && title !== main) candidates.push(title);
	if (language !== 'japanese' && nameJap && nameJap !== main && !candidates.includes(nameJap)) candidates.push(nameJap);

	return candidates;
}
