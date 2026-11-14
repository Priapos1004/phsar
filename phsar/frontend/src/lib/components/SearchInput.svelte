<script lang="ts">
	// A search box with its icon and a ✕ that empties it — an input like any other, so
	// `oninput` hears it. The ✕ leaves with the text it clears, so it hands focus to the box
	// first (rules/frontend.md, "A control that removes itself hands focus on first").
	import { Input } from '$lib/components/ui/input';
	import { Search, X } from 'lucide-svelte';
	import * as cls from '$lib/styles/classes';

	interface Props {
		value: string;
		placeholder: string;
		oninput?: () => void;
	}

	let { value = $bindable(''), placeholder, oninput }: Props = $props();

	let input = $state<HTMLInputElement | null>(null);

	function clear() {
		input?.focus();
		value = '';
		oninput?.();
	}
</script>

<div class="relative">
	<Search class="absolute left-2.5 top-1/2 -translate-y-1/2 size-4 text-muted-foreground" />
	<Input bind:ref={input} class="pl-8 pr-8" {placeholder} bind:value {oninput} />
	{#if value}
		<button
			type="button"
			onclick={clear}
			aria-label="Clear search"
			class="absolute right-2 top-1/2 -translate-y-1/2 text-muted-foreground hover:text-card-foreground {cls.hitArea}"
		>
			<X class="size-4" />
		</button>
	{/if}
</div>
