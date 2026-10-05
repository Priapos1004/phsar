<script lang="ts">
	interface Props {
		/** Muted label in front of the badges ("Source", "Studio"). */
		label: string;
		/** Values to render as clickable badges. Renders nothing when empty. */
		values: string[];
		/** Opens the search filtered to the clicked value. */
		onSelect: (value: string) => void;
	}

	let { label, values, onSelect }: Props = $props();
</script>

{#if values.length}
	<!-- The label sits in a fixed-width column so stacked rows start their first badge at
	     the same x, and wrapped badges stay in the badge column instead of under the label. -->
	<div class="flex items-start gap-x-2">
		<span class="w-14 shrink-0 py-0.5 text-muted-foreground font-medium">{label}</span>
		<div class="flex flex-wrap items-center gap-x-2 gap-y-1.5">
			{#each values as value}
				<button
					type="button"
					onclick={() => onSelect(value)}
					class="px-2.5 py-0.5 rounded-md font-medium bg-card-foreground/8 text-card-foreground border border-border hover:bg-card-foreground/15 hover:border-primary/50 transition cursor-pointer"
				>
					{value}
				</button>
			{/each}
		</div>
	</div>
{/if}
