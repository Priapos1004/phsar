<script lang="ts">
    import { X } from 'lucide-svelte';

    export let placeholder: string = 'Search and add...';
    export let options: string[] = [];
    export let selectedItems: string[] = [];
    export let onAdd: (item: string) => void;
    export let onRemove: (item: string) => void;

    let inputValue = '';
    let isFocused = false;
    let inputEl: HTMLInputElement;

    function handleSuggestionClick(option: string) {
        if (!selectedItems.includes(option)) {
            onAdd(option);
        }
        inputValue = '';
    }

    $: filteredOptions = options.filter(opt =>
        opt.toLowerCase().includes(inputValue.toLowerCase()) && !selectedItems.includes(opt)
    );

    function handleWrapperClick() {
        isFocused = true;
        setTimeout(() => inputEl?.focus(), 0);
    }
</script>

<div
    role="button"
    tabindex="0"
    class="w-full bg-white/80 backdrop-blur border border-purple-300 rounded-xl px-3 py-2 flex flex-wrap gap-2 items-center min-h-[48px] cursor-text"
    on:click={handleWrapperClick}
    on:keydown={(e) => { if (e.key === 'Enter' || e.key === ' ') handleWrapperClick(); }}
>
    {#each selectedItems as item}
        <span class="bg-purple-600 text-white px-3 py-1 rounded-full flex items-center text-sm">
            {item}
            <button type="button" class="ml-1 focus:outline-none" on:click={() => onRemove(item)}>
                <X class="w-4 h-4" />
            </button>
        </span>
    {/each}

    <input
        bind:this={inputEl}
        type="text"
        bind:value={inputValue}
        placeholder={selectedItems.length === 0 && inputValue === '' ? placeholder : ''}
        class="bg-transparent text-sm text-gray-800 placeholder-gray-500 focus:outline-none transition-all duration-200"
        class:w-0={!isFocused && inputValue === '' && selectedItems.length > 0}
        class:min-w-[100px]={isFocused || inputValue !== '' || selectedItems.length === 0}
        on:focus={() => isFocused = true}
        on:blur={() => setTimeout(() => isFocused = false, 150)}
    />
</div>

{#if isFocused}
    <div class="border border-purple-300 rounded-xl mt-1 bg-white/90 backdrop-blur shadow max-h-40 overflow-y-auto">
        {#if filteredOptions.length > 0}
            {#each filteredOptions as option}
                <button
                    type="button"
                    class="w-full text-left px-3 py-2 hover:bg-purple-100 text-sm text-gray-700 focus:outline-none"
                    on:click={() => handleSuggestionClick(option)}
                >
                    {option}
                </button>
            {/each}
        {:else}
            <div class="px-3 py-2 text-sm text-gray-500">No results found</div>
        {/if}
    </div>
{/if}
