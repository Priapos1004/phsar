<script lang="ts" module>
	import { decimalPlaces } from '$lib/utils/formatString';

	/** A slider's track, in slider units (log₂(v + 1) on a log scale). Its ends sit ON the
	 * step grid, floored and ceiled from the bounds: bits-ui snaps a thumb to the grid, and an
	 * end off it is a position the thumb can never rest at — the snap then reads as a value. */
	export interface SliderGrid {
		lo: number;
		hi: number;
		/** The catalogue's bounds, in values: a filter at or past one keeps everything. */
		min: number;
		max: number;
		step: number;
		log: boolean;
		digits: number;
	}

	// Below the step's precision, so floating-point drift never moves a position by a step.
	const EPS = 1e-9;

	export function sliderGrid(min: number, max: number, step: number, log = false): SliderGrid {
		const digits = decimalPlaces(step);
		const round = (x: number) => +x.toFixed(digits);
		return {
			step, log, digits, min, max,
			lo: round(Math.floor(toSlider(min, log) / step + EPS) * step),
			hi: round(Math.ceil(toSlider(max, log) / step - EPS) * step),
		};
	}

	function toSlider(value: number, log: boolean): number {
		return log ? Math.log2(Math.max(value, 0) + 1) : value;
	}

	function fromSlider(position: number, grid: SliderGrid): number {
		return grid.log ? Math.round(2 ** position - 1) : +position.toFixed(grid.digits);
	}

	/** A value's thumb position: on the grid, inside the track. */
	export function toGrid(value: number, grid: SliderGrid): number {
		const snapped = +(Math.round(toSlider(value, grid.log) / grid.step) * grid.step).toFixed(grid.digits);
		return Math.min(Math.max(snapped, grid.lo), grid.hi);
	}

	/** The filter value a thumb at `position` stands for. A thumb still where `current` put
	 * it keeps `current` verbatim — snapping it would change a value nobody touched. A thumb
	 * whose value reaches the catalogue's bound is no filter. Judged in values, not positions:
	 * the track's ends sit outside the bounds, and on a log track the first steps inside an
	 * end still round to the bound. */
	export function thumbValue(
		position: number, current: number | null | undefined, end: 'min' | 'max', grid: SliderGrid,
	): number | undefined {
		if (current != null && Math.abs(position - toGrid(current, grid)) < grid.step / 1000) return current;
		const value = fromSlider(position, grid);
		return (end === 'min' ? value <= grid.min : value >= grid.max) ? undefined : value;
	}
</script>

<script lang="ts">
	// A two-thumb range filter. It works in VALUE space — the caller passes and receives
	// filter values, an unset end as undefined — and keeps slider positions to itself.
	//
	// It writes only on `onValueCommit`, which fires when a user lets go of a thumb.
	// bits-ui also fires `onValueChange` when it snaps a value onto the step grid on its
	// own, with nobody touching the slider; writing on that turns a snap into a filter
	// the user never set. The live readout during a drag reads the local position instead.
	import { Slider } from '$lib/components/ui/slider';

	type Range = [number | undefined, number | undefined];

	interface Props {
		label: string;
		/** The catalogue's min and max — the track's ends, and an unset filter's readout. */
		bounds: [number, number];
		value: Range;
		step: number;
		log?: boolean;
		format: (value: number) => string;
		onCommit: (value: Range) => void;
	}

	let { label, bounds, value, step, log = false, format, onCommit }: Props = $props();

	let grid = $derived(sliderGrid(bounds[0], bounds[1], step, log));
	// Where the thumbs sit: the applied value until a drag moves them, an unset end at the
	// track's end — not at the bound's own position, which rounds to a step inside it.
	let position = $derived([
		value[0] == null ? grid.lo : toGrid(value[0], grid),
		value[1] == null ? grid.hi : toGrid(value[1], grid),
	]);

	const read = (pos: number[]): Range => [
		thumbValue(pos[0], value[0], 'min', grid),
		thumbValue(pos[1], value[1], 'max', grid),
	];
	let shown = $derived(read(position));
</script>

<div class="space-y-2">
	<div class="flex items-baseline justify-between gap-2">
		<span class="text-sm font-medium text-card-foreground">{label}</span>
		<span class="text-sm text-muted-foreground tabular-nums">
			{format(shown[0] ?? bounds[0])} – {format(shown[1] ?? bounds[1])}
		</span>
	</div>
	<Slider
		type="multiple"
		value={position}
		min={grid.lo}
		max={grid.hi}
		step={grid.step}
		onValueChange={(v) => (position = v)}
		onValueCommit={(v) => onCommit(read(v))}
	/>
</div>
