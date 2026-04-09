<script lang="ts">
	import { ChevronDown, ChevronUp } from 'lucide-svelte';
	import { formatDecimalDigits } from '$lib/utils/formatString';

	interface NoteItem {
		title: string;
		note: string;
		rating: number;
	}

	interface Props {
		notes: NoteItem[];
	}

	let { notes }: Props = $props();

	let expanded = $state(false);
	let visibleNotes = $derived(expanded ? notes : notes.slice(0, 1));
</script>

<div>
	<h3 class="text-sm font-medium text-muted-foreground mb-3">Your Notes</h3>

	<div class="space-y-2">
		{#each visibleNotes as item}
			<div class="bg-muted/50 rounded-lg px-4 py-3">
				<div class="flex items-center gap-2 mb-1">
					<span class="text-sm font-medium text-card-foreground">{item.title}</span>
					<span class="text-sm font-bold text-primary">{formatDecimalDigits(item.rating, 1)}</span>
				</div>
				<p class="text-card-foreground/80 italic leading-relaxed">
					"{item.note}"
				</p>
			</div>
		{/each}
	</div>

	{#if notes.length > 1}
		<button
			class="flex items-center gap-1.5 text-primary text-sm mt-2 group"
			onclick={() => (expanded = !expanded)}
		>
			{#if expanded}
				<ChevronUp class="size-4" />
				<span class="group-hover:underline">Show less</span>
			{:else}
				<ChevronDown class="size-4" />
				<span class="group-hover:underline">Show all {notes.length} notes</span>
			{/if}
		</button>
	{/if}
</div>
