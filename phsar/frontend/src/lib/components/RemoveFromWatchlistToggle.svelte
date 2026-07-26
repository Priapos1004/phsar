<script lang="ts">
	import { Checkbox } from '$lib/components/ui/checkbox';

	// Shared auto-checked "also remove from watchlist" attention block, used by RatingCard
	// (new-rating form + rewatch dialog) and BulkRateDialog. Yellow styling flags that
	// removing from the watchlist is a side effect worth noticing (not a plain checkbox).
	// The caller owns the checkbox state (bind:checked) and both copy lines, so the styling
	// + wiring can't drift across the three sites (cf. DeleteWatchHistoryToggle).
	interface Props {
		checked: boolean;
		label: string; // e.g. `Also remove from your "Watchlist" list` / `Also remove 3 media …`
		detail: string; // the muted help sentence below
	}
	let { checked = $bindable(), label, detail }: Props = $props();
</script>

<div class="rounded-lg border border-yellow-200 bg-yellow-50 px-3 py-2 space-y-1">
	<label class="flex items-center gap-2 text-sm font-medium text-yellow-800 cursor-pointer">
		<Checkbox bind:checked />
		{label}
	</label>
	<p class="text-xs text-neutral-600 pl-6">{detail}</p>
</div>
