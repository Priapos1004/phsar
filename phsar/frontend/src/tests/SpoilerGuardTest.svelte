<script lang="ts">
	import SpoilerGuard from '$lib/components/SpoilerGuard.svelte';

	interface Props {
		visible: boolean;
		mode: 'image' | 'text';
	}

	let { visible, mode }: Props = $props();
</script>

<SpoilerGuard {visible} {mode}>
	<p>Test Content</p>
</SpoilerGuard>
