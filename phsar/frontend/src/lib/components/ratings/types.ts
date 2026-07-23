// Top-level tabs of the /ratings page. Mirrors lib/components/admin/types.ts.
// Adding a tab means updating this union, the TABS array + content cascade in
// routes/ratings/+page.svelte (the shared data-driven TabNav needs no per-tab edit).
export type RatingsTabKey = 'ratings' | 'stats';

// Inner sections of the Statistics tab. Persisted in the ratingsFilter store (not
// the URL) so a round-trip to a detail page and back lands on the same section.
export type StatsSection = 'overview' | 'alignment' | 'tags' | 'attributes' | 'activity';
