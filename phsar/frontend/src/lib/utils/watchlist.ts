// Shared watchlist constants, used by the dialogs, the overview grid, and the Tags tab.
import { buildColorWheel } from './color';
import * as cls from '$lib/styles/classes';
import type { ReadyFilterKey, ReadyStatus } from './watchlistReady';

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

// How each readiness verdict renders on an anime-grain card/row, keyed by `ReadyStatus`
// so adding a verdict is a type error here until it is given a look. `ready` maps to
// undefined — no badge. Tints come from `styles/classes`, with the rest of the badge
// palette. The rules that produce these verdicts live in `utils/watchlistReady`.
interface ReadyBadge {
	label: string;
	class: string;
	title: string;
}

export const READY_BADGE: Record<ReadyStatus, ReadyBadge | undefined> = {
	ready: undefined,
	standalone: {
		label: 'Standalone',
		class: cls.badgeReadyStandalone,
		title: 'Long enough to watch on its own, even with the franchise still going',
	},
	hot: {
		label: 'Hot',
		class: cls.badgeReadyHot,
		title: "Airing now or returning next season — you can't binge it whole yet",
	},
	waiting: {
		label: 'Waiting',
		class: cls.badgeReadyWaiting,
		title: "Everything listed is watched — the rest hasn't aired",
	},
};

// The Status filter chips, selected-state styling included. Two of them describe the same
// verdict a badge does, so they read their wording AND their tint off it rather than
// restating either — a chip and the cards it admits must not explain or colour that
// verdict differently.
//
// A selected chip's fill is one of those fixed hues rather than `bg-primary`: a theme
// token is whatever the active theme makes it, so under the Ocean theme a primary-filled
// chip and a blue one are the same chip twice.
//
// Ready has no badge and borrows Standalone's green — it is the chip that admits
// standalone anime, so the two read as one family.
export const READY_FILTERS: (ReadyBadge & { key: ReadyFilterKey })[] = [
	{
		key: 'ready',
		label: 'Ready',
		title: 'Something to watch now, with no season airing or due next season',
		class: cls.badgeReadyStandalone,
	},
	{ key: 'hot', ...READY_BADGE.hot! },
	{ key: 'waiting', ...READY_BADGE.waiting! },
];

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
