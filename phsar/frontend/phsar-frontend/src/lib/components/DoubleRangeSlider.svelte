<script lang="ts">
	export let label: string = 'Select Range';
	export let minValue: number = 0;
	export let maxValue: number = 100;
	export let step: number = 1;
	export let from: number = minValue;
	export let to: number = maxValue;
	export let onChange: (val: { from: number; to: number }) => void = () => {};

	let minInput: number = from;
	let maxInput: number = to;

	// Detect external changes
	$: if (from !== undefined && from !== prevFrom) {
		minInput = from;
		prevFrom = from;
	}
	$: if (to !== undefined && to !== prevTo) {
		maxInput = to;
		prevTo = to;
	}

	let prevFrom = from;
	let prevTo = to;

	function validateInputs() {
		const clampedMin = Math.max(minValue, Math.min(minInput, maxValue));
		const clampedMax = Math.max(clampedMin, Math.min(maxInput, maxValue));

		// only update if needed to avoid loops
		if (clampedMin !== minInput || clampedMax !== maxInput) {
			minInput = clampedMin;
			maxInput = clampedMax;
		}

		onChange({ from: clampedMin, to: clampedMax });
	}
</script>

<div class="range-wrapper">
	<span class="range-label">{label}</span>

	<div class="range-inputs">
		<input
			type="number"
			bind:value={minInput}
			min={minValue}
			max={maxInput}
			step={step}
			on:input={validateInputs}
			class="range-field"
		/>
		<span class="range-separator">–</span>
		<input
			type="number"
			bind:value={maxInput}
			min={minInput}
			max={maxValue}
			step={step}
			on:input={validateInputs}
			class="range-field"
		/>
	</div>

	<div class="slider-container">
		<div class="slider-track"></div>
		<input
			type="range"
			min={minValue}
			max={maxValue}
			step={step}
			bind:value={maxInput}
			on:input={validateInputs}
			class="slider thumb-right"
		/>
		<input
			type="range"
			min={minValue}
			max={maxValue}
			step={step}
			bind:value={minInput}
			on:input={validateInputs}
			class="slider thumb-left"
		/>
	</div>
</div>

<style>
	.range-wrapper {
		width: 100%;
		padding: 1rem;
		background: rgba(255, 255, 255, 0.9);
		backdrop-filter: blur(12px);
		border-radius: 1rem;
		box-shadow: 0 4px 12px rgba(0, 0, 0, 0.05);
		display: flex;
		flex-direction: column;
		gap: 0.75rem;
	}

	.range-label {
		font-weight: 600;
		font-size: 0.9rem;
		color: #4b5563;
	}

	.range-inputs {
		display: flex;
		align-items: center;
		gap: 0.5rem;
	}

	.range-field {
		flex: 1;
		padding: 0.5rem 0.75rem;
		border-radius: 0.75rem;
		background: #f3f4f6;
		border: 1px solid #d1d5db;
		color: #111827;
		font-size: 0.875rem;
		font-weight: 500;
		appearance: textfield;
		transition: border 0.2s ease, box-shadow 0.2s ease;
		box-shadow: inset 0 1px 2px rgba(0, 0, 0, 0.03);
	}

	.range-field:focus {
		border-color: #a855f7;
		box-shadow: 0 0 0 3px rgba(168, 85, 247, 0.15);
		outline: none;
		background: white;
	}

	.range-separator {
		font-size: 0.875rem;
		color: #9ca3af;
	}

	input[type='number']::-webkit-inner-spin-button,
	input[type='number']::-webkit-outer-spin-button {
		-webkit-appearance: none;
		margin: 0;
	}
	input[type='number'] {
		-moz-appearance: textfield;
	}

	.slider-container {
		position: relative;
		height: 1.5rem;
		display: flex;
		align-items: center;
	}

	.slider-track {
		position: absolute;
		top: 50%;
		left: 0;
		right: 0;
		height: 6px;
		background-color: #e5e7eb;
		border-radius: 4px;
		transform: translateY(-50%);
	}

	.slider {
		position: absolute;
		width: 100%;
		height: 1.5rem;
		background: none;
		-webkit-appearance: none;
		pointer-events: none;
	}

	.slider::-webkit-slider-thumb {
		pointer-events: all;
		-webkit-appearance: none;
		height: 16px;
		width: 16px;
		border-radius: 50%;
		background: #a855f7;
		cursor: pointer;
		border: 2px solid white;
		box-shadow: 0 0 0 3px rgba(168, 85, 247, 0.2);
		transition: transform 0.15s ease;
	}

	.slider::-webkit-slider-thumb:hover {
		transform: scale(1.05);
	}

	.slider::-moz-range-thumb {
		pointer-events: all;
		height: 16px;
		width: 16px;
		border-radius: 50%;
		background: #a855f7;
		cursor: pointer;
		border: 2px solid white;
		box-shadow: 0 0 0 3px rgba(168, 85, 247, 0.2);
		transition: transform 0.15s ease;
	}

	.slider::-moz-range-thumb:hover {
		transform: scale(1.05);
	}
</style>