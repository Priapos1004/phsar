// Shared watchlist constants, used by the dialogs, the overview grid, and the Tags tab.

export const PRIORITY_OPTIONS = [
	{ value: 1, label: 'High' },
	{ value: 2, label: 'Medium' },
	{ value: 3, label: 'Low' },
] as const;

export function priorityLabel(p: number): string {
	return PRIORITY_OPTIONS.find((o) => o.value === p)?.label ?? 'Low';
}

// A `background` value for a set of tag colors: a single solid color, or — for an anime
// spanning several lists — a HARD-STOP gradient (crisp equal bands, not a fuzzy blend) so
// each list's color stays identifiable.
export function tagGradient(colors: string[]): string {
	if (colors.length <= 1) return colors[0] ?? '#888888';
	const n = colors.length;
	const stops = colors.map((c, i) => `${c} ${((i / n) * 100).toFixed(2)}% ${(((i + 1) / n) * 100).toFixed(2)}%`);
	return `linear-gradient(135deg, ${stops.join(', ')})`;
}

// Per-priority accent (text + a matching border tint) for the grid band headers + chips.
export const PRIORITY_ACCENT: Record<number, { text: string; dot: string }> = {
	1: { text: 'text-red-400', dot: 'bg-red-500' },
	2: { text: 'text-amber-400', dot: 'bg-amber-500' },
	3: { text: 'text-sky-400', dot: 'bg-sky-500' },
};

// Preset palette offered when creating/editing a tag. The default tag's reserved orange
// (#f97316) is deliberately NOT here, so a custom tag can't impersonate it.
export const TAG_COLOR_PALETTE = [
	'#ef4444', // red
	'#ec4899', // pink
	'#a855f7', // purple
	'#6366f1', // indigo
	'#3b82f6', // blue
	'#06b6d4', // cyan
	'#10b981', // emerald
	'#84cc16', // lime
	'#eab308', // yellow
	'#78716c', // stone
];
