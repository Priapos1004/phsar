<script lang="ts">
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
	import { formatDuration } from '$lib/utils/formatString';
	import { scoreGaugeOption } from '$lib/utils/chartTheme';
	import { totalWatchTime } from '$lib/utils/ratingStats';
	import { RATING_ATTRIBUTE_OPTIONS, getRatingAttr, isAttrRated, type RatingScoreItem } from '$lib/types/api';

	interface Props {
		items: RatingScoreItem[];
		ratingStep: number;
	}

	let { items, ratingStep }: Props = $props();

	// ── Summary metrics over the whole library ──────────────────────────────
	let totalRatings = $derived(items.length);
	let distinctAnime = $derived(new Set(items.map((i) => i.anime_uuid)).size);
	let avgScore = $derived(totalRatings ? items.reduce((s, i) => s + i.rating, 0) / totalRatings : 0);
	let completedCount = $derived(items.filter((i) => i.watch_status === 'completed').length);
	let onHoldCount = $derived(items.filter((i) => i.watch_status === 'on_hold').length);
	let droppedCount = $derived(items.filter((i) => i.watch_status === 'dropped').length);
	let totalWatchSeconds = $derived(totalWatchTime(items));

	let gaugeOption = $derived(scoreGaugeOption(avgScore));

	const ATTR_KEYS = Object.keys(RATING_ATTRIBUTE_OPTIONS);
	let hasAttributes = $derived(items.some((r) => ATTR_KEYS.some((k) => isAttrRated(getRatingAttr(r, k)))));

	// ── Inner tabs: only the active section mounts, so its charts animate in on
	// switch (ECharts plays its entrance animation on a fresh init) and we never
	// hold ~8 chart instances live at once. ──────────────────────────────────
	type Section = 'overview' | 'alignment' | 'tags' | 'attributes' | 'activity';
	const SECTIONS: { key: Section; label: string }[] = [
		{ key: 'overview', label: 'Overview' },
		{ key: 'alignment', label: 'You vs MAL' },
		{ key: 'tags', label: 'Genres & Studios' },
		{ key: 'attributes', label: 'Attributes' },
		{ key: 'activity', label: 'Activity' },
	];
	let active = $state<Section>('overview');
	let visibleSections = $derived(SECTIONS.filter((s) => s.key !== 'attributes' || hasAttributes));
</script>

<div class="space-y-5">
	<nav class="flex flex-wrap gap-2">
		{#each visibleSections as s (s.key)}
			<button
				onclick={() => (active = s.key)}
				class="px-3.5 py-1.5 rounded-full text-sm border transition-colors {active === s.key
					? 'border-primary bg-primary/15 text-primary font-medium'
					: 'border-white/15 text-white/60 hover:text-white hover:border-white/30'}"
			>{s.label}</button>
		{/each}
	</nav>

	{#if active === 'overview'}
		<Card.Root class={cls.cardGlass}>
			<Card.Content class="space-y-5">
				<div class="grid grid-cols-2 md:grid-cols-5 gap-4 items-center">
					<div class="flex flex-col items-center">
						<EChart option={gaugeOption} width="96px" height="96px" />
						<span class="text-sm text-muted-foreground -mt-2">Your average</span>
					</div>
					<div class="flex flex-col items-center justify-center">
						<span class="text-2xl font-bold text-card-foreground">{totalRatings}</span>
						<span class="text-sm text-muted-foreground">Ratings</span>
					</div>
					<div class="flex flex-col items-center justify-center">
						<span class="text-2xl font-bold text-card-foreground">{distinctAnime}</span>
						<span class="text-sm text-muted-foreground">Anime</span>
					</div>
					<div class="flex flex-col items-center justify-center gap-1">
						<span class="text-2xl font-bold text-card-foreground">{completedCount}</span>
						<div class="flex gap-1">
							{#if onHoldCount > 0}<Badge variant="secondary" class={cls.badgeOnHold}>{onHoldCount} hold</Badge>{/if}
							{#if droppedCount > 0}<Badge variant="destructive">{droppedCount} dropped</Badge>{/if}
						</div>
						<span class="text-sm text-muted-foreground">Completed</span>
					</div>
					<div class="flex flex-col items-center justify-center">
						<span class="text-2xl font-bold text-card-foreground">{formatDuration(totalWatchSeconds)}</span>
						<span class="text-sm text-muted-foreground">Watch time</span>
					</div>
				</div>
				<div>
					<p class="text-xs text-muted-foreground mb-1">Score distribution</p>
					<RatingsScoreHistogram {items} step={ratingStep} />
				</div>
			</Card.Content>
		</Card.Root>
	{:else if active === 'alignment'}
		<Card.Root class={cls.cardGlass}>
			<Card.Content class="space-y-3">
				<p class="text-sm text-muted-foreground">
					Each point is a rated title; bigger points have more MAL votes (more reliable scores).
				</p>
				<RatingsAlignmentChart {items} />
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
				<RatingsActivityChart {items} />
			</Card.Content>
		</Card.Root>
	{/if}

	<Notice>More statistics are on the way — taste clusters and a true watch-history timeline.</Notice>
</div>
