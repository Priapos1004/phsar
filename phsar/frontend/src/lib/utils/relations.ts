// The "main story" spine, shared by the ratings + watchlist overviews so both split
// an anime's media the same way. Main = the canonical chain plus alternative-version
// retellings (matches the backend RELATION_SCORE_WEIGHTS + the spoiler frontier anchor
// set); everything else (side stories, summaries) counts as side.
export const MAIN_RELATIONS = new Set(['main', 'alternative_version']);

/** "X main · Y side" breakdown for the anime-grain cards + tables. A 0 count is
 * omitted, so a side-story-only anime reads "1 side". */
export function mainSideLabel(main: number, side: number): string {
	return [main ? `${main} main` : null, side ? `${side} side` : null].filter(Boolean).join(' · ');
}
