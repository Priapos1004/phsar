<script lang="ts">
	import { X } from 'lucide-svelte';
	import * as cls from '$lib/styles/classes';

	export let placeholder: string = 'Search and add...';
	export let options: string[] = [];
	export let selectedItems: string[] = [];
	export let onAdd: (item: string) => void;
	export let onRemove: (item: string) => void;

	let inputValue = '';
	let isFocused = false;
	let inputEl: HTMLInputElement;

	const MAX_ITEMS = 5;
	let showLimitHint = false;
	let hintTimeout: ReturnType<typeof setTimeout> | null = null;

	$: isAtLimit = selectedItems.length >= MAX_ITEMS;

	$: filteredOptions = options.filter(opt =>
		opt.toLowerCase().includes(inputValue.toLowerCase()) && !selectedItems.includes(opt)
	);

	function handleSuggestionClick(option: string) {
		if (!selectedItems.includes(option)) {
			if (isAtLimit) {
				showLimitHint = true;
				if (hintTimeout) clearTimeout(hintTimeout);
				hintTimeout = setTimeout(() => {
					showLimitHint = false;
				}, 2000);
				return;
			}

			onAdd(option);
			inputValue = '';
		}
	}

	function handleWrapperClick() {
		isFocused = true;
		setTimeout(() => inputEl?.focus(), 0);
	}
</script>

<div
	role="button"
	tabindex="0"
	class="relative w-full bg-white/80 backdrop-blur border border-purple-300 rounded-xl px-3 py-2 flex flex-wrap gap-2 items-center min-h-[48px] cursor-text"
	on:click={handleWrapperClick}
	on:keydown={(e) => { if (e.key === 'Enter' || e.key === ' ') handleWrapperClick(); }}
>
	{#each selectedItems as item}
		<span class={cls.tag}>
			{item}
			<button type="button" class={cls.tagClose} on:click={() => onRemove(item)}>
				<X class="w-4 h-4" />
			</button>
		</span>
	{/each}

	<input
		bind:this={inputEl}
		type="text"
		bind:value={inputValue}
		placeholder={selectedItems.length === 0 && inputValue === '' ? placeholder : ''}
		class="bg-transparent text-sm text-gray-800 placeholder-gray-500 focus:outline-none"
		class:w-0={!isFocused && inputValue === '' && selectedItems.length > 0}
		class:min-w-[100px]={isFocused || inputValue !== '' || selectedItems.length === 0}
		on:focus={() => isFocused = true}
		on:blur={() => setTimeout(() => isFocused = false, 150)}
	/>

	{#if showLimitHint}
		<div class="bg-red-600 text-white text-xs rounded-lg px-3 py-1 shadow-sm">
			You can select up to {MAX_ITEMS} items only.
		</div>
	{/if}
</div>

{#if isFocused}
	<div class="border border-purple-300 rounded-xl mt-1 bg-white/90 backdrop-blur shadow max-h-40 overflow-y-auto">
		{#if filteredOptions.length > 0}
			{#each filteredOptions as option}
				<button
					type="button"
					class="w-full text-left px-3 py-2 text-sm hover:bg-purple-100 text-gray-700 focus:outline-none"
					on:click={() => handleSuggestionClick(option)}
				>
					{option}
				</button>
			{/each}
		{:else}
			<div class="px-3 py-2 text-sm text-gray-500">No options found</div>
		{/if}
	</div>
{/if}
