/** Display ordering for the server's dump-restorability verdict.
 *
 * The verdict ITSELF (`BackupMetadata.status`) is computed server-side, in the
 * same `list_backups` pass that derives `schema_current`. It has to be: the
 * startup self-heal decides whether to take a fresh dump on the same question the
 * card renders, and when this file owned the composite the two disagreed — a dump
 * with no recorded revision showed a green `ok` pill while the backend had just
 * decided nothing on disk was restorable. One producer, several consumers.
 *
 * What's left here is presentation: worst-first ordering for the "By
 * restorability" sort. `unknown` outranks `outdated` because an unverified dump is
 * probably fine, whereas an outdated one definitely would roll the schema back.
 */

import type { BackupMetadata, BackupStatus } from '$lib/types/api';

/** Worst first. Doubles as the source of the status union, so a new verdict can't
 * be added to the type without being given a rank. */
export const DUMP_STATUS_ORDER = ['corrupt', 'outdated', 'unknown', 'ok'] as const;

function rank(status: BackupStatus): number {
	const i = DUMP_STATUS_ORDER.indexOf(status);
	// An unrecognised verdict (server ahead of this build) sorts as the worst
	// thing we can say about it, rather than silently as the best.
	return i === -1 ? -1 : i;
}

/** Comparator for the "By restorability" sort: worst status first, then newest
 * within a status. */
export function compareByRestorability(a: BackupMetadata, b: BackupMetadata): number {
	const diff = rank(a.status) - rank(b.status);
	if (diff !== 0) return diff;
	return new Date(b.created_at).getTime() - new Date(a.created_at).getTime();
}
