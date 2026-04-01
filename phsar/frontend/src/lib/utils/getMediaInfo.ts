/**
 * Calculate total watchtime in seconds from episodes and duration per episode.
 */
export function calculateWatchtime(episodes: number | null, durationSeconds: number | null): number | null {
    if (episodes == null || durationSeconds == null) {
        return null;
    }
    return episodes * durationSeconds;
}
