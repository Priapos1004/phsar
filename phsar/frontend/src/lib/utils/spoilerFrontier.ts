/**
 * Client-side spoiler frontier computation.
 *
 * Mirrors the backend algorithm in spoiler_service.py:
 * determines which media within an anime are visible (not spoiler-protected)
 * based on user's watch progress through the main story backbone.
 */

const SEASON_ORDER: Record<string, number> = {
	Winter: 1,
	Spring: 2,
	Summer: 3,
	Fall: 4
};

interface MediaForFrontier {
	uuid: string;
	relation_type: string;
	anime_season_year: number | null;
	anime_season_name: string | null;
}

function chronologicalSortKey(m: MediaForFrontier): [number, number, string] {
	return [
		m.anime_season_year ?? 9999,
		SEASON_ORDER[m.anime_season_name ?? ''] ?? 0,
		m.uuid // Stable tiebreaker (backend uses mal_id, but UUID works for client-side)
	];
}

function compareSortKeys(a: [number, number, string], b: [number, number, string]): number {
	if (a[0] !== b[0]) return a[0] - b[0];
	if (a[1] !== b[1]) return a[1] - b[1];
	return a[2].localeCompare(b[2]);
}

/**
 * Compute which media UUIDs in an anime are visible based on the spoiler frontier.
 *
 * @param media - All media items within a single anime (from detail page)
 * @param ratedUuids - Set of media UUIDs the user has rated
 * @returns Set of visible media UUIDs
 */
export function computeVisibleMediaUuids(
	media: MediaForFrontier[],
	ratedUuids: Set<string>
): Set<string> {
	if (media.length === 0) return new Set();

	const sorted = [...media].sort((a, b) =>
		compareSortKeys(chronologicalSortKey(a), chronologicalSortKey(b))
	);

	// Find main media indices
	const mainIndices = sorted
		.map((m, i) => (m.relation_type === 'main' ? i : -1))
		.filter((i) => i !== -1);

	if (mainIndices.length === 0) {
		// No main media — only first media visible
		return new Set([sorted[0].uuid]);
	}

	// Find last rated main media index
	let lastRatedMainIdx = -1;
	for (const idx of mainIndices) {
		if (ratedUuids.has(sorted[idx].uuid)) {
			lastRatedMainIdx = idx;
		}
	}

	let frontierIdx: number;

	if (lastRatedMainIdx === -1) {
		// No main rated — frontier is first main
		frontierIdx = mainIndices[0];
	} else {
		// Find next unrated main after last rated
		let nextUnrated: number | null = null;
		for (const idx of mainIndices) {
			if (idx > lastRatedMainIdx && !ratedUuids.has(sorted[idx].uuid)) {
				nextUnrated = idx;
				break;
			}
		}

		if (nextUnrated === null) {
			// All main rated — everything visible
			return new Set(sorted.map((m) => m.uuid));
		}

		frontierIdx = nextUnrated;
	}

	// Visible: everything up to the frontier, plus any individually rated
	// media beyond it (e.g. a side story the user explicitly watched)
	const visible = new Set<string>();
	for (let i = 0; i < sorted.length; i++) {
		if (i <= frontierIdx || ratedUuids.has(sorted[i].uuid)) {
			visible.add(sorted[i].uuid);
		}
	}
	return visible;
}
