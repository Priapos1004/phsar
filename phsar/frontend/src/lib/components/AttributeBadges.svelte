<!-- TODO(v0.15.1): Verify mobile layout — orbital pills may overlap on narrow viewports -->
<script lang="ts">
	import type { AnimeMediaItem, RatingOut } from '$lib/types/api';
	import { BADGE_KEYS, aggregateBadges } from '$lib/utils/ratingAttributes';

	interface Props {
		ratings: RatingOut[];
		/** The anime's media, for the relation and chronology `aggregateBadges` needs.
		 *  Optional — `buildPools` covers the media-grain case. */
		media?: AnimeMediaItem[];
		/**
		 * `responsive` (default) picks the wrap on mobile and the orbit on desktop.
		 * `wrap` pins the wrap at every width — what the fixed-size share card needs:
		 * the orbit's pills overhang their 240px box by ~50px a side (fine inside a
		 * half-width page column, but a fixed-width card has no slack to absorb it),
		 * and a viewport-dependent layout would make the same rating export differently
		 * from a phone than from a desktop.
		 */
		layout?: 'responsive' | 'wrap';
	}

	let { ratings, media, layout = 'responsive' }: Props = $props();

	// One decision, derived once — two independent conditions could render both layouts.
	let showOrbit = $derived(layout === 'responsive');

	// Where each pill sits on the orbit and how far it tilts in each layout. Keyed by
	// attribute rather than positionally, so reordering BADGE_KEYS cannot silently move
	// a pill's geometry onto a different attribute. Rotations are deliberately irregular
	// for an organic, tossed-on-table feel.
	//
	// `wrapRotation` is much gentler than the orbit's tilt because flex lays out the
	// UNROTATED boxes: a tilt adds ±(width · sin θ)/2 of vertical reach the row gap has to
	// absorb, and 8° on a ~290px pill needs 20px per side — which is what made adjacent
	// wrapped rows collide. 2–3° needs ~8px, comfortably inside gap-y-5.
	const PILL_STYLES: Record<string, { angle: number; rotation: number; wrapRotation: number }> = {
		pace: { angle: 20, rotation: -6, wrapRotation: -2 },              // top-right
		has_3d_animation: { angle: 72, rotation: 4, wrapRotation: 1.5 },  // right
		watched_format: { angle: 118, rotation: -8, wrapRotation: -3 },   // bottom-right — raised to avoid fan service collision
		fan_service: { angle: 200, rotation: 5, wrapRotation: 2 },        // bottom-left
		ending_type: { angle: 252, rotation: -3, wrapRotation: -1.5 },    // left
		originality: { angle: 303, rotation: 7, wrapRotation: 2.5 },      // top-left — lowered to avoid collision with pace
	};

	interface PillData {
		key: string;
		label: string;
		value: string | null;
	}

	// Each pill answers a different question, so each aggregates differently — the rules
	// and their reasoning live in `aggregateBadges`.
	let pills = $derived<PillData[]>(aggregateBadges(ratings, media));

	let glowing = $state<boolean[]>(Array(BADGE_KEYS.length).fill(false));

	function triggerGlow(index: number) {
		// Reset to retrigger if already animating
		glowing[index] = false;
		requestAnimationFrame(() => { glowing[index] = true; });
	}

	function clearGlow(index: number) {
		glowing[index] = false;
	}
</script>

{#snippet pill(b: PillData, index: number, extraClass: string, extraStyle: string)}
	<span
		class="rounded-full px-3 py-1 text-xs font-medium cursor-default select-none
			transition-transform duration-200 hover:scale-110 hover:!rotate-0
			{b.value ? 'bg-primary/10 text-card-foreground' : 'bg-muted/50 text-muted-foreground'}
			{extraClass}"
		class:pill-glow={glowing[index]}
		style={extraStyle}
		onclick={() => triggerGlow(index)}
		onanimationend={() => clearGlow(index)}
		role="presentation"
	>
		{b.label}: <strong>{b.value ?? '--'}</strong>
	</span>
{/snippet}

<!-- Mobile (and every width when pinned to `wrap`): scattered flex wrap -->
<div class="flex flex-wrap justify-center gap-x-2 gap-y-5 {showOrbit ? 'md:hidden' : ''}">
	{#each pills as p, i}
		{@render pill(p, i, 'inline-block', `transform: rotate(${PILL_STYLES[p.key].wrapRotation}deg);`)}
	{/each}
</div>

<!-- Desktop: orbital ellipse arrangement -->
{#if showOrbit}
<div class="hidden md:block relative" style="width: 240px; height: 200px;">
	{#each pills as p, i}
		{@const angle = PILL_STYLES[p.key].angle}
		{@const rot = PILL_STYLES[p.key].rotation}
		{@const radX = 112}
		{@const radY = 80}
		{@const x = 120 + radX * Math.cos((angle - 90) * Math.PI / 180)}
		{@const y = 100 + radY * Math.sin((angle - 90) * Math.PI / 180)}
		{@render pill(
			p, i,
			'absolute -translate-x-1/2 -translate-y-1/2 whitespace-nowrap',
			`left: ${x}px; top: ${y}px; rotate: ${rot}deg;`,
		)}
	{/each}
</div>
{/if}

<style>
	@keyframes pill-burst {
		0%   { background-color: var(--color-chart-1); box-shadow: 0 0 8px 2px color-mix(in oklch, var(--color-chart-1) 60%, transparent); }
		20%  { background-color: var(--color-chart-5); box-shadow: 0 0 14px 4px color-mix(in oklch, var(--color-chart-5) 50%, transparent); }
		40%  { background-color: var(--color-chart-3); box-shadow: 0 0 18px 6px color-mix(in oklch, var(--color-chart-3) 40%, transparent); }
		60%  { background-color: var(--color-chart-2); box-shadow: 0 0 14px 4px color-mix(in oklch, var(--color-chart-2) 50%, transparent); }
		80%  { background-color: var(--color-chart-4); box-shadow: 0 0 8px 2px color-mix(in oklch, var(--color-chart-4) 60%, transparent); }
		100% { background-color: transparent; box-shadow: 0 0 0 0 transparent; }
	}

	.pill-glow {
		animation: pill-burst 1.2s ease-out forwards;
	}
</style>
