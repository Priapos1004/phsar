<script lang="ts">
	import { X } from 'lucide-svelte';
	import * as cls from '$lib/styles/classes';
	import { fade } from 'svelte/transition';

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
	$: filteredOptions = options
		.filter(opt => opt.toLowerCase().includes(inputValue.toLowerCase()) && !selectedItems.includes(opt));

	function handleSuggestionClick(option: string) {
		if (isAtLimit) {
			showLimitHint = true;
			if (hintTimeout) clearTimeout(hintTimeout);
			hintTimeout = setTimeout(() => showLimitHint = false, 2000);
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
	<!-- Input + tags -->
	<div
		role="button"
		tabindex="0"
		class="bg-white/80 backdrop-blur border border-purple-300 rounded-xl px-3 py-2 flex flex-wrap gap-2 items-center min-h-[48px] cursor-text"
		on:click={handleWrapperClick}
		on:keydown={(e) => (e.key === 'Enter' || e.key === ' ') && handleWrapperClick()}
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
			placeholder={selectedItems.length === 0 && !inputValue ? placeholder : ''}
			class="bg-transparent text-sm text-gray-800 placeholder-gray-500 focus:outline-none"
			class:w-0={!isFocused && !inputValue && selectedItems.length > 0}
			class:min-w-[100px]={isFocused || inputValue !== '' || selectedItems.length === 0}
			on:focus={() => isFocused = true}
			on:blur={() => setTimeout(() => isFocused = false, 150)}
		/>

		{#if showLimitHint}
            <div
                in:fade={{ duration: 200 }}
                out:fade={{ duration: 400 }}
                class="absolute top-[-1.5rem] right-0 text-xs bg-red-500 text-white px-3 py-1 rounded-lg shadow z-50"
            >
                ⚠ Max 5 items
            </div>
        {/if}
	</div>

	<!-- Floating dropdown -->
	{#if isFocused}
		<div
			class="absolute z-50 left-0 right-0 mt-1 bg-white/95 backdrop-blur-sm border border-purple-300 rounded-xl shadow-md max-h-40 overflow-y-auto"
		>
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
</div>
