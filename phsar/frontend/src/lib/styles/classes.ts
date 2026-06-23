/** Shared Tailwind class strings for reuse across components */

// Layout
export const container = 'max-w-5xl mx-auto px-4';
export const sectionSpacing = 'space-y-8';

// MediaInfo
export const mediaInfoGrid = 'grid grid-cols-1 lg:grid-cols-2 gap-4 auto-rows-fr';

// Badge colors (color only — composable with size variants)
export const badgeMediaTypeColor = 'bg-green-100 text-green-800';
export const badgeRelationTypeColor = 'bg-blue-100 text-blue-800';
export const badgeGenreColor = 'bg-primary/10 text-primary';
export const badgeAgeRatingColor = 'bg-orange-100 text-orange-800';
// On-hold watch status (amber) — shared so RatingCard + RatingsOverviewStats can't drift.
export const badgeOnHold = 'bg-amber-100 text-amber-800 border-amber-200';
// Dropped watch status (solid rose) — same visual weight as on-hold, for the ratings
// list where the translucent built-in `destructive` variant read too faint.
export const badgeDropped = 'bg-rose-100 text-rose-800 border-rose-200';
// Story-complete (emerald) — shared by the anime-page badge + the anime search card badge.
export const badgeComplete = 'bg-emerald-100 text-emerald-800 border-emerald-200';

// Badge defaults for normal-sized contexts (hero card, search cards)
const badgeSize = 'text-sm h-auto px-2.5 py-0.5';
export const badgeMediaType = `${badgeMediaTypeColor} ${badgeSize}`;
export const badgeRelationType = `${badgeRelationTypeColor} ${badgeSize}`;
export const badgeGenre = `${badgeGenreColor} ${badgeSize}`;
export const badgeAgeRating = `${badgeAgeRatingColor} ${badgeSize}`;

// Card glass effect
export const cardGlass = 'bg-card/80 backdrop-blur';
