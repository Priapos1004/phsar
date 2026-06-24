<script lang="ts" generics="T extends string | number">
	// On-card segmented toggle: a muted pill track with a solid-primary thumb on the
	// active option. Lives on the WHITE card surface (ratings stats + filter bar), so
	// inactive text is card-foreground (dark), never the light page `foreground` token.
	// `value` is the option to highlight and may be a DERIVED value distinct from what
	// onSelect writes (e.g. the moving-average window clamps to the dataset), so the
	// caller owns both the source of truth and the write — this component is presentational.
	interface Option {
		value: T;
		label: string;
	}
	interface Props {
		options: Option[];
		value: T;
		onSelect: (value: T) => void;
		/** sm (px-2.5 py-0.5) sits inline next to a chart caption; md (px-3 py-1) pairs with a heading. */
		size?: 'sm' | 'md';
		ariaLabel?: string;
	}

	let { options, value, onSelect, size = 'sm', ariaLabel }: Props = $props();

	let pad = $derived(size === 'md' ? 'px-3 py-1' : 'px-2.5 py-0.5');
</script>

<div class="inline-flex rounded-full bg-muted p-0.5 text-xs" role="group" aria-label={ariaLabel}>
	{#each options as opt (opt.value)}
		<button
			type="button"
			onclick={() => onSelect(opt.value)}
			class="{pad} rounded-full transition-colors {value === opt.value
				? 'bg-primary text-white shadow-sm'
				: 'text-card-foreground/70 hover:text-card-foreground'}"
		>{opt.label}</button>
	{/each}
</div>
