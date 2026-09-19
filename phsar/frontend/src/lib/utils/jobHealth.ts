import type { AdminJobKindStats } from '$lib/types/api';

export interface JobHealthWindowGroup {
	days: number;
	rows: AdminJobKindStats[];
}

/**
 * Group the admin Job health rows by the window their counts cover.
 *
 * `/admin/stats/overview` emits one flat row per `JobKind`, in enum order, so
 * the windows arrive **interleaved** — separating them is the work here, not
 * cosmetics. Shortest window first; backend order is preserved within each
 * group, so the card's row order stays the server's.
 *
 * Same shape as `toScoreBands` / `toPriorityBands`: bucket into a Map, order
 * the keys, emit `{key, rows}`. The group object mirrors those two rather
 * than returning bare `[days, rows]` tuples, so call sites read by name.
 */
export function byWindow(rows: AdminJobKindStats[]): JobHealthWindowGroup[] {
	const groups = new Map<number, AdminJobKindStats[]>();
	for (const row of rows) {
		const existing = groups.get(row.window_days);
		if (existing) existing.push(row);
		else groups.set(row.window_days, [row]);
	}
	return [...groups.entries()]
		.sort(([a], [b]) => a - b)
		.map(([days, kinds]) => ({ days, rows: kinds }));
}
