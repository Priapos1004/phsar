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
