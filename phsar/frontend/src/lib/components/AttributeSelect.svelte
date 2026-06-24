<script lang="ts">
	import * as Select from '$lib/components/ui/select';
	import { Label } from '$lib/components/ui/label';
	import { X } from 'lucide-svelte';

	interface Props {
		label: string;
		/** Full option list incl. the `not_applicable` sentinel (used for the trigger
		 *  label lookup); the sentinel is filtered out of the selectable dropdown below. */
		options: { value: string; label: string }[];
		value: string | null;
		onChange: (value: string | null) => void;
		/** Auto-managed fields (the ending fields on an unfinished watch) disable the
		 *  control and hide the clear button. */
		disabled?: boolean;
	}

	let { label, options, value, onChange, disabled = false }: Props = $props();

	// `not_applicable` is an auto-set-only sentinel — never user-selectable in any
	// dropdown (single source of truth so bulk + media can't drift). The trigger still
	// resolves its label from the full `options` so an auto-set value reads "Not Applicable".
	let selectable = $derived(options.filter((o) => o.value !== 'not_applicable'));
	let selectedLabel = $derived(options.find((o) => o.value === value)?.label ?? 'Select...');
</script>

<div class="space-y-1">
	<Label class={value ? 'text-card-foreground font-medium' : 'text-muted-foreground'}>
		{label}
	</Label>
	<div class="relative">
		<Select.Root
			type="single"
			value={value ?? undefined}
			onValueChange={(val: string) => onChange(val || null)}
			{disabled}
		>
			<Select.Trigger class="w-full {value ? 'bg-primary/5 border-2 border-primary/40' : 'bg-card'}">
				{#if value}
					{selectedLabel}
				{:else}
					<span class="text-muted-foreground">Not set</span>
				{/if}
			</Select.Trigger>
			<Select.Content>
				{#each selectable as option}
					<Select.Item value={option.value}>{option.label}</Select.Item>
				{/each}
			</Select.Content>
		</Select.Root>
		{#if value && !disabled}
			<!-- Clear-to-deselect: sits left of the trigger's chevron. stopPropagation so it
			     clears instead of opening the dropdown. -->
			<button
				type="button"
				class="absolute top-1/2 right-8 -translate-y-1/2 z-10 text-muted-foreground hover:text-foreground"
				onclick={(e) => { e.stopPropagation(); onChange(null); }}
				aria-label={`Clear ${label}`}
			>
				<X class="size-3.5" />
			</button>
		{/if}
	</div>
</div>
