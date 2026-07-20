<script lang="ts">
	import { Check } from 'lucide-svelte';
	import { TAG_COLOR_PALETTE } from '$lib/utils/watchlist';

	interface Props {
		value: string;
	}

	let { value = $bindable() }: Props = $props();
</script>

<div class="flex flex-wrap gap-2">
	{#each TAG_COLOR_PALETTE as color (color)}
		<button
			type="button"
			class="size-7 rounded-full ring-2 ring-offset-2 ring-offset-card transition {value === color ? 'ring-card-foreground' : 'ring-transparent hover:ring-border'}"
			style="background:{color}"
			aria-label={`Color ${color}`}
			onclick={() => (value = color)}
		>
			{#if value === color}
				<Check class="size-4 text-white mx-auto" />
			{/if}
		</button>
	{/each}
</div>
