<script lang="ts">
	// An ⓘ beside a header or a setting whose meaning the page doesn't spell out — the
	// explanation a chip or a select can't carry itself (rules/frontend.md, "Tooltips").
	import Tooltip from '$lib/components/Tooltip.svelte';
	import { Info } from 'lucide-svelte';
	import * as cls from '$lib/styles/classes';

	interface Props {
		/** The icon's accessible name — what the tooltip explains. */
		label: string;
		text?: string;
		/** A key under `text`: each term in bold before its meaning. */
		terms?: { label: string; title: string }[];
	}

	let { label, text, terms }: Props = $props();
</script>

<Tooltip class="relative flex text-muted-foreground {cls.hitArea}">
	{#snippet content()}
		<div class="space-y-1.5">
			{#if text}<p>{text}</p>{/if}
			{#if terms}
				<dl class="space-y-1.5">
					{#each terms as term (term.label)}
						<div><dt class="inline font-semibold">{term.label}</dt> <dd class="inline">{term.title}</dd></div>
					{/each}
				</dl>
			{/if}
		</div>
	{/snippet}
	<Info class="size-3.5" aria-hidden="true" />
	<span class="sr-only">{label}</span>
</Tooltip>
