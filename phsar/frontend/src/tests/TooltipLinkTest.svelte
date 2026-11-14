<script lang="ts">
	// A children-mode tooltip inside a link, as a tile's cover marker sits, beside a
	// trigger-mode one on a button: tooltip.test.ts taps both.
	import Tooltip from '$lib/components/Tooltip.svelte';

	let { insideLink = false, onact = () => {} }: { insideLink?: boolean; onact?: () => void } = $props();
</script>

<a href="/anime">
	<Tooltip text="The definition" {insideLink}><span>Label</span></Tooltip>
</a>
<Tooltip text="The action" {insideLink}>
	{#snippet trigger(props)}
		<button {...props} type="button" onclick={onact}>Act</button>
	{/snippet}
</Tooltip>
