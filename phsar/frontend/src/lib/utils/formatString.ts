import { RELATION_TYPE_LABELS } from '$lib/utils/chartColors';

/** Formats a raw relation_type value to a user-friendly label. */
export function formatRelationType(type: string): string {
	return RELATION_TYPE_LABELS[type] ?? type;
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
 * Strip MAL attribution tags (e.g. "[Written by MAL Rewrite]") from description text.
 */
export function cleanDescription(text: string): string {
	return text.replace(/\s*\[Written by MAL Rewrite\]\s*/g, '').trim();
}

/**
 * Clamp a score to [0, 10] and round to the nearest step.
 * Examples (step=0.5): 6.6 -> 6.5, 9.656 -> 9.5, -1 -> 0, 15 -> 10, 7.25 -> 7.5
 * Examples (step=1):   6.6 -> 7, 9.3 -> 9, 0.4 -> 0
 */
export function clampAndSnapScore(val: number, step: number): number {
	const clamped = Math.min(10, Math.max(0, val));
	return Math.round(clamped / step) * step;
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
	if (language === 'romaji') return title;
	// Fallback: english name → romaji title
	return nameEng ?? title;
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
