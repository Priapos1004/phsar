<script lang="ts">
	import Tooltip from '$lib/components/Tooltip.svelte';

	interface Props {
		/** "Top N%" rank (1 = best). Renders nothing when null (unscored). */
		topPercent: number | null;
	}

	let { topPercent }: Props = $props();

	// Color ramps by tier: top → emerald, above median → sky, below → neutral.
	// Solid light tones match the badge palette in styles/classes.ts (detail
	// cards are light surfaces).
	function tone(p: number): string {
		if (p <= 15) return 'bg-emerald-100 text-emerald-800 border-emerald-200';
		if (p <= 50) return 'bg-sky-100 text-sky-800 border-sky-200';
		return 'bg-muted text-muted-foreground border-border';
	}
</script>

<!-- Always-visible chip (no hover needed → works on mobile); the tooltip only
     adds the full explanation. -->
{#if topPercent !== null}
	{@const explanation = `Higher MyAnimeList score than ${100 - topPercent}% of titles in Phsar's catalog. Ranked by score weighted by vote count, so a high score from few votes doesn't rank top.`}
	<Tooltip text={explanation}>
		<span class="text-xs font-semibold rounded-full px-2 py-0.5 border whitespace-nowrap {tone(topPercent)}">
			Top {topPercent}%
		</span>
	</Tooltip>
{/if}
