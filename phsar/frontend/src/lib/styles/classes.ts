/** Shared Tailwind class strings for reuse across components */

// Layout
export const container = 'max-w-5xl mx-auto px-4';
export const sectionSpacing = 'space-y-8';
export const sectionHeader = 'text-2xl font-semibold mb-4 text-white';

// ScrollableCard
export const card = 'bg-white/80 backdrop-blur rounded-xl p-4 shadow';

// MediaInfo
export const mediaInfoGrid = 'grid grid-cols-1 lg:grid-cols-2 gap-4 auto-rows-fr';

// Input
export const input = 'w-full px-5 py-3 rounded-full bg-white/80 backdrop-blur border border-gray-300 focus:outline-none focus:ring-2 focus:ring-purple-500 pr-12';

// Tag in TagSelect
export const tag = 'bg-purple-600 text-white px-3 py-1 rounded-full flex items-center text-sm';
export const tagClose = 'ml-1 focus:outline-none';

// === Tag base style (shared across media_type, genre, relation_type) ===
export const tagBase = 'text-xs px-2 py-1 rounded-full';

// === Tag type styles ===
export const tagGenre = 'bg-purple-100 text-purple-800';
export const tagMediaType = 'bg-green-100 text-green-800';
export const tagRelation = 'bg-blue-100 text-blue-800';

// Button
export const iconButton = 'text-purple-700 hover:text-purple-500';

// Blur wrapper
export const blurBox = 'mt-3 bg-white/80 backdrop-blur rounded-xl p-4 shadow space-y-4';
