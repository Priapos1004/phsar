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
	let trigger = $state<HTMLElement | null>(null);

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
			<!-- Once set, the ✕ takes the chevron's place (the chevron stays, invisible, holding
			     its space): beside it, the two leave a long value too little room. -->
			<Select.Trigger bind:ref={trigger} class="w-full {value ? 'bg-primary/5 border-2 border-primary/40' : 'bg-card'} {value && !disabled ? '[&>svg]:invisible' : ''}">
				{#if value}
					<span class="truncate">{selectedLabel}</span>
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
			<!-- Clear-to-deselect, over the hidden chevron. stopPropagation so it clears instead
			     of opening the dropdown; focus to the trigger first, since the ✕ leaves with the
			     value (rules/frontend.md, "A control that removes itself hands focus on first"). -->
			<button
				type="button"
				class="absolute top-1/2 right-3 -translate-y-1/2 z-10 text-muted-foreground hover:text-foreground"
				onclick={(e) => { e.stopPropagation(); trigger?.focus(); onChange(null); }}
				aria-label={`Clear ${label}`}
			>
				<X class="size-4" />
			</button>
		{/if}
	</div>
</div>
