<!-- TODO(v0.15.1): Verify mobile layout — orbital pills may overlap on narrow viewports -->
<script lang="ts">
	import { RATING_ATTRIBUTE_OPTIONS, getRatingAttr } from '$lib/types/api';
	import type { RatingOut } from '$lib/types/api';

	interface Props {
		ratings: RatingOut[];
	}

	let { ratings }: Props = $props();

	const BADGE_KEYS = [
		'pace',
		'has_3d_animation',
		'watched_format',
		'fan_service',
		'ending_type',
		'originality',
	];

	// Each pill gets a fixed rotation and position on a circle (clockwise from top-right).
	// Rotations are deliberately irregular for an organic, tossed-on-table feel.
	const PILL_STYLES = [
		{ angle: 20, rotation: -6 },   // top-right (pace)
		{ angle: 72, rotation: 4 },    // right (3d animation)
		{ angle: 118, rotation: -8 },  // bottom-right (watched format) — raised to avoid fan service collision
		{ angle: 200, rotation: 5 },   // bottom-left (fan service)
		{ angle: 252, rotation: -3 },  // left (ending type)
		{ angle: 308, rotation: 7 },   // top-left (originality) — lowered to avoid collision with pace
	];

	interface PillData {
		label: string;
		value: string | null;
	}

	let pills = $derived.by<PillData[]>(() =>
		BADGE_KEYS.map((key) => {
			const config = RATING_ATTRIBUTE_OPTIONS[key];
			const counts = new Map<string, number>();

			for (const r of ratings) {
				const val = getRatingAttr(r, key);
				if (val) {
					counts.set(val, (counts.get(val) ?? 0) + 1);
				}
			}

			// Find majority value; on ties, first in options order wins
			let majorityValue: string | null = null;
			let majorityCount = 0;
			for (const opt of config.options) {
				const c = counts.get(opt.value) ?? 0;
				if (c > majorityCount) {
					majorityValue = opt.value;
					majorityCount = c;
				}
			}

			const displayValue = majorityValue
				? (config.options.find((o) => o.value === majorityValue)?.label ?? majorityValue)
				: null;
			return { label: config.label, value: displayValue };
		}),
	);

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

<!-- Mobile: scattered flex wrap -->
<div class="flex flex-wrap justify-center gap-2 md:hidden">
	{#each pills as p, i}
		{@render pill(p, i, 'inline-block', `transform: rotate(${PILL_STYLES[i].rotation}deg);`)}
	{/each}
</div>

<!-- Desktop: orbital ellipse arrangement -->
<div class="hidden md:block relative" style="width: 240px; height: 200px;">
	{#each pills as p, i}
		{@const angle = PILL_STYLES[i].angle}
		{@const rot = PILL_STYLES[i].rotation}
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

<style>
	@keyframes pill-burst {
		0%   { background-color: var(--color-chart-1); box-shadow: 0 0 8px 2px oklch(0.558 0.288 302.321 / 0.6); }
		20%  { background-color: var(--color-chart-5); box-shadow: 0 0 14px 4px oklch(0.645 0.246 16.439 / 0.5); }
		40%  { background-color: var(--color-chart-3); box-shadow: 0 0 18px 6px oklch(0.769 0.188 70.08 / 0.4); }
		60%  { background-color: var(--color-chart-2); box-shadow: 0 0 14px 4px oklch(0.696 0.17 162.48 / 0.5); }
		80%  { background-color: var(--color-chart-4); box-shadow: 0 0 8px 2px oklch(0.627 0.265 303.9 / 0.6); }
		100% { background-color: transparent; box-shadow: 0 0 0 0 transparent; }
	}

	.pill-glow {
		animation: pill-burst 1.2s ease-out forwards;
	}
</style>
