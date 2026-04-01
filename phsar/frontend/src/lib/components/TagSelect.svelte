<script lang="ts">
	import { X } from 'lucide-svelte';
	import { Badge } from '$lib/components/ui/badge';

	interface Props {
		placeholder?: string;
		options?: string[];
		selectedItems?: string[];
		onAdd: (item: string) => void;
		onRemove: (item: string) => void;
	}

	let {
		placeholder = 'Search and add...',
		options = [],
		selectedItems = [],
		onAdd,
		onRemove,
	}: Props = $props();

	let inputValue = $state('');
	let isFocused = $state(false);
	let inputEl: HTMLInputElement | undefined = $state();

	const MAX_ITEMS = 5;
	let showLimitHint = $state(false);

	$effect(() => {
		if (showLimitHint) {
			const id = setTimeout(() => (showLimitHint = false), 2000);
			return () => clearTimeout(id);
		}
	});

	let isAtLimit = $derived(selectedItems.length >= MAX_ITEMS);
	let filteredOptions = $derived(
		options.filter(
			(opt) => opt.toLowerCase().includes(inputValue.toLowerCase()) && !selectedItems.includes(opt)
		)
	);

	function handleSelect(option: string) {
		if (isAtLimit) {
			showLimitHint = true;
			return;
		}
		onAdd(option);
		inputValue = '';
	}

	function handleWrapperClick() {
		isFocused = true;
		setTimeout(() => inputEl?.focus(), 0);
	}
</script>

<div class="relative w-full">
	<div
		role="button"
		tabindex="0"
		class="bg-card/80 backdrop-blur border border-input rounded-xl px-3 py-2 flex flex-wrap gap-2 items-center min-h-[48px] cursor-text"
		onclick={handleWrapperClick}
		onkeydown={(e) => (e.key === 'Enter' || e.key === ' ') && handleWrapperClick()}
	>
		{#each selectedItems as item}
			<Badge variant="default" class="gap-1 text-sm h-6">
				{item}
				<button
					type="button"
					class="ml-1 hover:opacity-70"
					onclick={(e) => { e.stopPropagation(); onRemove(item); }}
				>
					<X class="w-3 h-3" />
				</button>
			</Badge>
		{/each}

		<input
			bind:this={inputEl}
			type="text"
			bind:value={inputValue}
			placeholder={selectedItems.length === 0 && !inputValue ? placeholder : ''}
			class="bg-transparent text-sm text-card-foreground placeholder:text-muted-foreground focus:outline-none"
			class:w-0={!isFocused && !inputValue && selectedItems.length > 0}
			class:min-w-[100px]={isFocused || inputValue !== '' || selectedItems.length === 0}
			onfocus={() => (isFocused = true)}
			onblur={() => setTimeout(() => (isFocused = false), 150)}
		/>

		{#if showLimitHint}
			<div class="absolute top-[-1.5rem] right-0 text-xs bg-destructive text-white px-3 py-1 rounded-lg shadow z-50">
				Max {MAX_ITEMS} items
			</div>
		{/if}
	</div>

	{#if isFocused && filteredOptions.length > 0}
		<div class="absolute z-50 left-0 right-0 mt-1 bg-popover border border-border rounded-xl shadow-md max-h-40 overflow-y-auto">
			{#each filteredOptions as option}
				<button
					type="button"
					class="w-full text-left px-4 py-2 text-sm text-popover-foreground hover:bg-accent hover:text-accent-foreground"
					onmousedown={() => handleSelect(option)}
				>
					{option}
				</button>
			{/each}
		</div>
	{/if}

	{#if isFocused && filteredOptions.length === 0 && inputValue}
		<div class="absolute z-50 left-0 right-0 mt-1 bg-popover border border-border rounded-xl shadow-md">
			<div class="px-4 py-2 text-sm text-muted-foreground">No options found</div>
		</div>
	{/if}
</div>
