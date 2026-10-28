<script lang="ts">
	// The MyAnimeList score row of both detail heroes — one component, so the sibling pages
	// can't drift apart (rules/frontend.md, "Parallel pages stay parallel").
	import { Star } from 'lucide-svelte';
	import ScorePercentile from '$lib/components/ScorePercentile.svelte';
	import Tooltip from '$lib/components/Tooltip.svelte';
	import * as cls from '$lib/styles/classes';
	import { formatDecimalDigits, formatNumber } from '$lib/utils/formatString';

	interface Props {
		score: number;
		votes: number;
		/** "ratings" for one media, "ratings/media" for an anime's average. */
		votesLabel: string;
		/** What the score is — the tooltip on the pill. */
		hint: string;
		topPercent: number | null;
	}

	let { score, votes, votesLabel, hint, topPercent }: Props = $props();
</script>

<!-- Wraps on a phone, where the pill, the count and the Top badge overflow one line; the
     pill and the count never break inside. -->
<div class="flex flex-wrap items-center gap-x-3 gap-y-2">
	<Tooltip text={hint}>
		<span class="flex items-center gap-1.5 whitespace-nowrap bg-primary/10 rounded-full px-3 py-1.5">
			<Star class={cls.glassIcon} aria-hidden="true" />
			<span class="text-lg font-bold text-card-foreground">{formatDecimalDigits(score, 2)}</span>
			<span class="text-muted-foreground">/ 10</span>
		</span>
	</Tooltip>
	<span class="whitespace-nowrap text-muted-foreground">{formatNumber(votes)} {votesLabel}</span>
	<ScorePercentile {topPercent} />
</div>
