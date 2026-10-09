<script lang="ts" generics="T extends string">
	// The page-surface toggle; why it isn't SegmentedControl is rules/frontend.md, "A
	// toggle's surface decides its component". Presentational: the caller owns the truth
	// via `value` + `onSelect`.
	// `type="button"` because it sits inside the search form, where a bare button submits.
	import Tooltip from '$lib/components/Tooltip.svelte';

	interface Option {
		value: T;
		label: string;
		/** Shown but not selectable — a guest sees what the account could do. */
		disabled?: boolean;
		/** Tooltip text, e.g. why an option is disabled. */
		hint?: string;
	}
	interface Props {
		options: Option[];
		value: T;
		onSelect: (value: T) => void;
		ariaLabel?: string;
	}

	let { options, value, onSelect, ariaLabel }: Props = $props();

	const ON = 'bg-primary/15 text-primary font-medium';
	const OFF = 'text-white/60 hover:text-white';
	const DISABLED = 'text-white/30 cursor-not-allowed';
</script>

{#snippet pill(opt: Option, first: boolean, props: Record<string, unknown>)}
	<button
		{...props}
		type="button"
		class="px-3 py-1.5 text-sm transition-colors {first ? '' : 'border-l border-white/15'} {opt.disabled ? DISABLED : value === opt.value ? ON : OFF}"
		aria-pressed={value === opt.value}
		aria-disabled={opt.disabled}
		onclick={() => !opt.disabled && onSelect(opt.value)}
	>
		{opt.label}
	</button>
{/snippet}

<div class="inline-flex rounded-full border border-white/15 overflow-hidden" role="group" aria-label={ariaLabel}>
	{#each options as opt, i (opt.value)}
		{#if opt.hint}
			<Tooltip text={opt.hint}>
				{#snippet trigger(props)}{@render pill(opt, i === 0, props)}{/snippet}
			</Tooltip>
		{:else}
			{@render pill(opt, i === 0, {})}
		{/if}
	{/each}
</div>
