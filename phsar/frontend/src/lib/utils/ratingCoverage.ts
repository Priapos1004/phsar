import type { CoverageTier } from '$lib/types/api';

/**
 * How each coverage tier marks a card.
 *
 * This lives on the CARD, not on the cover art: anything overlaying an image
 * reads as part of it, and cover art varies too much for a mark on it to stay
 * legible. What each tier means is in docs/features/ratings.md.
 *
 * - **`edge`** and **`hairline`** are the two-tone card edge: the metal, plus a
 *   line in the opposite key beside it. The second tone is what keeps the edge
 *   visible against both the light and the dark theme background — a near-black
 *   edge alone disappears on a dark page. They stay COLOURS rather than one
 *   composed `box-shadow`, because the two cards draw the edge with different
 *   properties: `/search` can use `box-shadow` (it displaces a static ring that
 *   `Card.Root` sets and nothing animates), while the `/ratings` card must use
 *   `outline` — its box-shadow is a composed Tailwind chain (`shadow-sm` plus
 *   two `group-hover:` variants) that an inline box-shadow would beat, costing
 *   marked cards their hover lift.
 * - **`band`** paints the card: an inward-fading band on search, a flat footer
 *   tint on `/ratings`. Gradients need a large area to read across, which is why
 *   the metal is legible here and was not in a band around the cover.
 * - **`foreground`** is the text colour `band` demands where it backs text.
 *
 * The literal colours are the documented exception to "theme tokens only" in
 * `.claude/rules/frontend.md`, for the reason `WATCHTIME_FILTERS` takes it: gold
 * and obsidian have to mean gold and obsidian under all four themes. `some` is
 * the theme token precisely because it is the ordinary tier.
 */
export const COVERAGE_STYLE: Record<
	CoverageTier,
	{ edge: string; hairline?: string; band: string; foreground?: string; label: string }
> = {
	all: {
		edge: '#0b0e13',
		hairline: 'rgba(226,232,240,0.6)',
		band: 'linear-gradient(135deg,#1b2027 0%,#05070a 18%,#39414b 38%,#0d1117 52%,#2b323b 72%,#06080b 100%)',
		foreground: '#e8edf3',
		label: 'Every aired entry rated'
	},
	main: {
		edge: '#c9922f',
		hairline: 'rgba(48,31,4,0.7)',
		band: 'linear-gradient(135deg,#f0c964 0%,#a8761b 18%,#ffeeb4 38%,#c9922f 52%,#e8c35e 72%,#96681a 100%)',
		foreground: '#241803',
		label: 'Every aired main-story entry rated'
	},
	some: {
		edge: 'var(--primary)',
		band: 'var(--primary)',
		label: 'Partly rated'
	}
};

/**
 * What the `/ratings` grid should draw for a tier.
 *
 * Every card on that page is rated by definition, so the base tier is true of all
 * of them and carries no information — drawing it would mark the whole grid.
 */
export function ratingsGridTier(tier: CoverageTier | undefined): CoverageTier | null {
	return tier && tier !== 'some' ? tier : null;
}
