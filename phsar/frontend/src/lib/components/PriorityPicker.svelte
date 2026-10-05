<script lang="ts">
	// The 3-button High/Medium/Low priority picker, shared by the watchlist dialogs.
	// `undefined` renders with nothing selected — the bulk dialog's state when the
	// entries it would rewrite disagree, so the user has to pick rather than inherit
	// a default that would quietly downgrade one of them.
	import { PRIORITY_OPTIONS } from '$lib/utils/watchlist';

	interface Props {
		value: number | undefined;
	}

	let { value = $bindable() }: Props = $props();
</script>

<div class="grid grid-cols-3 gap-2">
	{#each PRIORITY_OPTIONS as opt}
		<button
			type="button"
			class="rounded-md border px-3 py-2 text-sm font-medium transition
				{value === opt.value
					? 'border-primary bg-primary/10 text-primary'
					: 'border-border bg-card text-muted-foreground hover:border-primary/40'}"
			onclick={() => (value = opt.value)}
		>
			{opt.label}
		</button>
	{/each}
</div>
