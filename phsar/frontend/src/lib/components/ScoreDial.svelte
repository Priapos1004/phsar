<script lang="ts">
	import { Slider } from '$lib/components/ui/slider';
	import { clampAndSnapScore } from '$lib/utils/formatString';

	interface Props {
		// The raw 0–10 score. Bindable — both the numeric input (on blur) and the slider
		// write snapped values back through it.
		score: number;
		// Snap increment = the user's rating step (e.g. 0.5).
		step: number;
		// Decimals to render in the numeric input (the step's precision).
		decimals: number;
	}

	let { score = $bindable(), step, decimals }: Props = $props();

	// Defensive re-snap for display so a bound value that skipped the slider/input (e.g. a
	// stored rating loaded into the edit form) still renders on-step.
	let snappedScore = $derived(clampAndSnapScore(score, step));
</script>

<!-- Editable score circle + slider. Circle/input sized so the widest value "10.00" (two
     integer digits + a 0.01-step's decimals) fits without the input clipping on the right.
     Shared by RatingCard + BulkRateDialog (was byte-identical inline in each). -->
<div class="flex flex-col items-center py-2 space-y-3">
	<div class="w-24 h-24 rounded-full bg-primary/10 border-2 border-primary/30 flex items-center justify-center">
		<input
			type="text"
			inputmode="decimal"
			value={snappedScore.toFixed(decimals)}
			onblur={(e) => {
				const parsed = parseFloat(e.currentTarget.value.replace(',', '.')) || 0;
				const snapped = clampAndSnapScore(parsed, step);
				score = snapped;
				e.currentTarget.value = snapped.toFixed(decimals);
			}}
			onkeydown={(e) => { if (e.key === 'Enter') e.currentTarget.blur(); }}
			class="w-20 text-center text-2xl font-bold text-card-foreground bg-transparent outline-none"
		/>
	</div>
	<div class="w-full max-w-xs">
		<Slider type="single" bind:value={score} min={0} max={10} {step} />
	</div>
</div>
