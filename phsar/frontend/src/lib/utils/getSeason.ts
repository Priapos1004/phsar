/** Canonical within-year ordering of anime seasons (Winter → Fall). Mirrors the
 * backend `filter_service.SEASON_ORDER`; the single frontend source so the spoiler
 * frontier, the ratings season filter, and any future season sort can't disagree on
 * order. Used only relatively, so the 1-based offset is immaterial. */
export const SEASON_ORDER: Record<string, number> = {
	Winter: 1,
	Spring: 2,
	Summer: 3,
	Fall: 4,
};

export function getCurrentSeason(): string {
    const date = new Date();
    const month = date.getMonth() + 1; // getMonth() → 0–11, so add 1 to get 1–12
    const year = date.getFullYear();

    let season: string;

    if (month >= 1 && month <= 3) {
        season = "Winter";
    } else if (month >= 4 && month <= 6) {
        season = "Spring";
    } else if (month >= 7 && month <= 9) {
        season = "Summer";
    } else if (month >= 10 && month <= 12) {
        season = "Fall";
    } else {
        season = "Unknown";
    }

    return `${season} ${year}`;
}
