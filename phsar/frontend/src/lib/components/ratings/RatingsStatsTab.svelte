<script lang="ts">
	import { MediaQuery } from 'svelte/reactivity';
	import * as Card from '$lib/components/ui/card';
	import { Badge } from '$lib/components/ui/badge';
	import EChart from '$lib/components/EChart.svelte';
	import Notice from '$lib/components/Notice.svelte';
	import RatingsScoreHistogram from './RatingsScoreHistogram.svelte';
	import RatingsAlignmentChart from './RatingsAlignmentChart.svelte';
	import RatingsTagChart from './RatingsTagChart.svelte';
	import RatingsAttributeAnalysis from './RatingsAttributeAnalysis.svelte';
	import RatingsActivityChart from './RatingsActivityChart.svelte';
	import * as cls from '$lib/styles/classes';
	import { formatDurationCompact } from '$lib/utils/formatString';
	import { scoreGaugeOption } from '$lib/utils/chartTheme';
	import { totalWatchTime } from '$lib/utils/ratingStats';
	import { ratingsFilter } from '$lib/stores/ratingsFilter';
	import type { StatsSection } from './types';
	import type { RatingScoreItem } from '$lib/types/api';
	import { hasAnyAttribute } from '$lib/utils/ratingAttributes';

	interface Props {
		items: RatingScoreItem[];
		ratingStep: number;
	}

	let { items, ratingStep }: Props = $props();

	// ── Summary metrics over the whole library ──────────────────────────────
	let totalRatings = $derived(items.length);
	let distinctAnime = $derived(new Set(items.map((i) => i.anime_uuid)).size);
	let avgScore = $derived(totalRatings ? items.reduce((s, i) => s + i.rating, 0) / totalRatings : 0);
	let onHoldCount = $derived(items.filter((i) => i.watch_status === 'on_hold').length);
	let droppedCount = $derived(items.filter((i) => i.watch_status === 'dropped').length);
	let totalWatchSeconds = $derived(totalWatchTime(items));

	// The gauge scales with `cls.statFigure` (the why is there); it is a chart, so its size is
	// set here.
	const twoXl = new MediaQuery(cls.twoXlUp);
	let gaugeSize = $derived(twoXl.current ? 120 : 96);
	let gaugeOption = $derived(scoreGaugeOption(avgScore, gaugeSize));
	// A figure over its label: a column on a phone, from md three rows of the overview's subgrid.
	const STAT = 'flex flex-col items-center justify-center md:row-[2/span_3] md:grid md:grid-rows-subgrid md:justify-items-center';

	let hasAttributes = $derived(hasAnyAttribute(items));

	// ── Inner tabs: only the active section mounts, so its charts animate in on
	// switch (ECharts plays its entrance animation on a fresh init) and we never
	// hold ~8 chart instances live at once. ──────────────────────────────────
	const SECTIONS: { key: StatsSection; label: string }[] = [
		{ key: 'overview', label: 'Overview' },
		{ key: 'alignment', label: 'You vs MAL' },
		// Key stays `tags` (the persisted store value + the StatsSection type) while the
		// label generalized — the section covers four dimensions since v0.15.3.
		{ key: 'tags', label: 'Categories' },
		{ key: 'attributes', label: 'Attributes' },
		{ key: 'activity', label: 'Activity' },
	];
	let visibleSections = $derived(SECTIONS.filter((s) => s.key !== 'attributes' || hasAttributes));
	// Active section lives in the store so a round-trip to a detail page lands back here.
	// Fall back to Overview if the persisted section isn't currently available (e.g.
	// Attributes hidden when no attributes are rated).
	let active = $derived(
		visibleSections.some((s) => s.key === $ratingsFilter.statsSection) ? $ratingsFilter.statsSection : 'overview',
	);
	function setSection(key: StatsSection) {
		ratingsFilter.update((f) => ({ ...f, statsSection: key }));
	}
</script>

<div class="space-y-5">
	<nav class="flex flex-wrap gap-2">
		{#each visibleSections as s (s.key)}
			<button
				onclick={() => setSection(s.key)}
				class="{cls.pagePill} {active === s.key ? cls.pagePillOn : cls.pagePillOff}"
			>{s.label}</button>
		{/each}
	</nav>

	{#if active === 'overview'}
		<Card.Root class={cls.cardGlass}>
			<Card.Content class="space-y-5">
				<!-- From md one row spread edge to edge, as the watchlist's overview: equal columns
				     would leave half a column empty at each end. The figures share three rows
				     (subgrid) — figure, label, the badges only Ratings has — so the figures sit on one
				     line and the badges end level with "Your average"; the gauge spans them plus a
				     first row that takes its extra height. On a phone (2×2) the items bottom-align, so
				     the badges still end level with "Your average". -->
				<div class="grid grid-cols-2 gap-4 items-end md:grid-cols-[repeat(4,auto)] md:grid-rows-[1fr_auto_auto_auto] md:justify-between md:items-stretch md:gap-y-0 md:px-4">
					<div class="flex flex-col items-center md:row-[1/span_4]">
						<EChart option={gaugeOption} width="{gaugeSize}px" height="{gaugeSize}px" />
						<span class="{cls.statLabel} -mt-2">Your average</span>
					</div>
					<!-- Ratings = the whole library; the hold/dropped badges sit underneath to
					     show they're a subset already counted in the total above. -->
					<div class="{STAT} max-md:gap-1">
						<span class={cls.statFigure}>{totalRatings}</span>
						<span class={cls.statLabel}>Ratings</span>
						{#if onHoldCount > 0 || droppedCount > 0}
							<div class="flex flex-wrap justify-center gap-1 md:pt-1">
								{#if onHoldCount > 0}<Badge variant="secondary" class={cls.badgeOnHold}>{onHoldCount} hold</Badge>{/if}
								{#if droppedCount > 0}<Badge variant="secondary" class={cls.badgeDropped}>{droppedCount} dropped</Badge>{/if}
							</div>
						{/if}
					</div>
					<div class={STAT}>
						<span class={cls.statFigure}>{distinctAnime}</span>
						<span class={cls.statLabel}>Anime</span>
					</div>
					<div class={STAT}>
						<!-- Compact, as the watchlist's Queued time: to the second, it wraps on a phone. -->
						<span class={cls.statFigure}>{formatDurationCompact(totalWatchSeconds)}</span>
						<span class={cls.statLabel}>Watch time</span>
					</div>
				</div>
				<div>
					<p class="text-sm font-medium text-card-foreground mb-1">Score distribution</p>
					<RatingsScoreHistogram {items} />
				</div>
			</Card.Content>
		</Card.Root>
	{:else if active === 'alignment'}
		<Card.Root class={cls.cardGlass}>
			<Card.Content class="space-y-3">
				<p class="text-sm text-muted-foreground">
					Each point is a rated title (bigger = more MAL votes, so more reliable). Green sits
					above your trend line (you rate it higher than your MAL pattern predicts), rose below.
				</p>
				<RatingsAlignmentChart {items} {ratingStep} />
			</Card.Content>
		</Card.Root>
	{:else if active === 'tags'}
		<Card.Root class={cls.cardGlass}>
			<Card.Content>
				<RatingsTagChart {items} />
			</Card.Content>
		</Card.Root>
	{:else if active === 'attributes'}
		<Card.Root class={cls.cardGlass}>
			<Card.Content>
				<RatingsAttributeAnalysis {items} />
			</Card.Content>
		</Card.Root>
	{:else if active === 'activity'}
		<Card.Root class={cls.cardGlass}>
			<Card.Content>
				<RatingsActivityChart {items} {ratingStep} />
			</Card.Content>
		</Card.Root>
	{/if}

	<Notice>More statistics are on the way — taste clusters and a true watch-history timeline.</Notice>
</div>
