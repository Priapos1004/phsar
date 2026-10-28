<script lang="ts">
	// Single-select dropdown of the user's watchlist tags, each with its color swatch.
	// Shared by WatchlistDialog + BulkWatchlistDialog (the drift source the codebase
	// closes by extraction, cf. AttributeSelect for the rating pair).
	import * as Select from '$lib/components/ui/select';
	import { tags } from '$lib/stores/tags';

	interface Props {
		value: string | undefined;
	}

	let { value = $bindable() }: Props = $props();

	let selectedTag = $derived($tags.find((t) => t.uuid === value));
</script>

<Select.Root type="single" bind:value>
	<Select.Trigger class="w-full bg-card">
		{#if selectedTag}
			<!-- Truncates: a list name in a control (rules/frontend.md, "A user's string can be one long word"). -->
			<span class="flex items-center gap-2 min-w-0">
				<!-- Faint border so a white/light list color stays visible on the card. -->
				<span class="size-3 shrink-0 rounded-full border border-border" style="background:{selectedTag.color}"></span>
				<span class="truncate" title={selectedTag.name}>{selectedTag.name}</span>
			</span>
		{:else}
			<span class="text-muted-foreground">Select a list</span>
		{/if}
	</Select.Trigger>
	<!-- Cap at ~5 rows and scroll the rest (the primitive already sets overflow-y-auto). No
	     wider than the trigger, so a long name truncates instead of widening the list. -->
	<Select.Content class="max-h-48 max-w-(--bits-select-anchor-width)">
		{#each $tags as tag}
			<Select.Item value={tag.uuid}>
				<span class="flex items-center gap-2 min-w-0">
					<span class="size-3 shrink-0 rounded-full border border-border" style="background:{tag.color}"></span>
					<span class="truncate" title={tag.name}>{tag.name}</span>
				</span>
			</Select.Item>
		{/each}
	</Select.Content>
</Select.Root>
