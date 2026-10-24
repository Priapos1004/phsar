<script lang="ts">
	// The attribute selects of a rating — one grid for the rating form and the bulk dialog,
	// so a layout fix reaches both.
	import AttributeSelect from '$lib/components/AttributeSelect.svelte';
	import { RATING_ATTRIBUTE_OPTIONS } from '$lib/types/api';

	interface Props {
		attributes: Record<string, string | null>;
		/** Fields the caller manages itself (an unfinished watch's ending fields). */
		isDisabled?: (key: string) => boolean;
	}

	let { attributes = $bindable(), isDisabled = () => false }: Props = $props();
</script>

<!-- Two columns while each can be 9.5rem wide (a long value like "Very Satisfying" beside
     its ✕), else one, never more than two — sized by the grid's own width, not the screen's:
     the bulk dialog is narrower than the page. On a phone that is one relaxed column. -->
<div class="grid grid-cols-[repeat(auto-fit,minmax(max(9.5rem,calc((100%_-_0.75rem)/2)),1fr))] gap-3 mt-3">
	{#each Object.entries(RATING_ATTRIBUTE_OPTIONS) as [key, config]}
		<AttributeSelect
			label={config.label}
			options={config.options}
			value={attributes[key] ?? null}
			onChange={(v) => (attributes[key] = v)}
			disabled={isDisabled(key)}
		/>
	{/each}
</div>
