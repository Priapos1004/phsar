<script lang="ts">
	import * as cls from '$lib/styles/classes';

	export let title: string;
	export let text: string;
	export let className: string = '';
</script>

{#if title}
    <h3 class={cls.sectionHeader}>{title}</h3>
{/if}
<div class={`${cls.card} space-y-2 ${className}`}>
	{#if text}
		<p class="text-gray-700">{text}</p>
	{/if}
</div>
