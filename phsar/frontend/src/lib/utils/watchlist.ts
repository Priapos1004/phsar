// Shared watchlist constants, used by the dialogs, the overview grid, and the Tags tab.
import { buildColorWheel } from './color';

export const PRIORITY_OPTIONS = [
	{ value: 1, label: 'High' },
	{ value: 2, label: 'Medium' },
	{ value: 3, label: 'Low' },
] as const;

export function priorityLabel(p: number): string {
	return PRIORITY_OPTIONS.find((o) => o.value === p)?.label ?? 'Low';
}

// Join an anime's per-media notes for the grid/table hover tooltip: one note per line with a
// divider rule between them. Single-sourced so the grid card + table render the same tooltip
// (both pair it with `contentClass="whitespace-pre-line"` so the newlines actually break).
export function joinNoteTexts(texts: string[]): string {
	return texts.join('\n──────────\n');
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

// The color a new custom list starts on — taken straight from a wheel cell (a vivid blue)
// so it's always pre-selected in the picker AND clickable again to restore. A hardcoded hex
// outside the wheel couldn't be re-selected without refreshing the page.
//
// A function, not a const: as a const this built the whole 37-cell wheel at module
// scope, and this module is imported by every surface that renders a bookmark — so
// each of them paid for a value only the list-color picker ever reads.
export function defaultNewTagColor(): string {
	return buildColorWheel()[2][1].hex;
}

// The default "Watchlist" list's reserved orange (mirrors tag_service.DEFAULT_TAG_COLOR).
// The color picker blocks a custom list from picking it, so the default stays visually unique.
export const RESERVED_DEFAULT_TAG_COLOR = '#f97316';
