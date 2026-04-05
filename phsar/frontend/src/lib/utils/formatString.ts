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
