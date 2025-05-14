<script lang="ts">
	export let title: string;
	export let score: number;
	export let scoredBy: number;
</script>

<div class="bg-white/80 backdrop-blur rounded-xl p-4 shadow space-y-2">
	<h3 class="font-bold text-lg">{title}</h3>
	<p class="text-xs text-gray-500">Score: {score} By: {scoredBy}</p>
</div>
