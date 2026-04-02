<script lang="ts">
	import * as Card from '$lib/components/ui/card';

	interface Props {
		title: string;
		text: string;
		class?: string;
	}

	let { title, text, class: className = '' }: Props = $props();
</script>

{#if title}
    <h3 class="text-2xl font-semibold mb-4 text-foreground">{title}</h3>
{/if}
<Card.Root class={`bg-card/80 backdrop-blur ${className}`}>
	<Card.Content>
		{#if text}
			<p class="text-card-foreground">{text}</p>
		{/if}
	</Card.Content>
</Card.Root>
