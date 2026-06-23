// Top-level tabs of the /ratings page. Mirrors lib/components/admin/types.ts.
// Adding a tab means updating this union, the TABS array + content cascade in
// routes/ratings/+page.svelte, and RatingsTabNav.
export type RatingsTabKey = 'ratings' | 'stats';
