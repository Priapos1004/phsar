<script lang="ts">
	import { Slider } from '$lib/components/ui/slider';

	interface Props {
		label?: string;
		minValue?: number;
		maxValue?: number;
		step?: number;
		from?: number;
		to?: number;
		onChange?: (val: { from: number; to: number }) => void;
		formatDisplay?: (val: number) => string;
	}

	let {
		label = 'Select Range',
		minValue = 0,
		maxValue = 100,
		step = 1,
		from = minValue,
		to = maxValue,
		onChange = () => {},
		formatDisplay = (val: number) => `${val}`,
	}: Props = $props();

	let value = $derived([from, to]);

	function handleValueChange(newValue: number[]) {
		onChange({ from: newValue[0], to: newValue[1] });
	}
</script>

<div class="w-full p-4 bg-card/90 backdrop-blur rounded-2xl shadow-sm space-y-3">
	<span class="font-semibold text-sm text-card-foreground">{label}</span>

	<div class="flex items-center gap-2">
		<div class="flex-1 px-3 py-2 rounded-xl bg-muted border border-border text-card-foreground text-sm font-medium">
			{formatDisplay(value[0])}
		</div>
		<span class="text-sm text-muted-foreground">–</span>
		<div class="flex-1 px-3 py-2 rounded-xl bg-muted border border-border text-card-foreground text-sm font-medium">
			{formatDisplay(value[1])}
		</div>
	</div>

	<Slider
		type="multiple"
		{value}
		min={minValue}
		max={maxValue}
		{step}
		onValueChange={handleValueChange}
	/>
</div>
