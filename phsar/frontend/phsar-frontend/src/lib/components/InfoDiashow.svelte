<script lang="ts">
	import { getCurrentSeason } from '$lib/utils/getSeason';

	const currentSeason = getCurrentSeason();
</script>

<div class="bg-purple-700 text-white rounded-2xl p-6 shadow-lg flex flex-col items-center">
    <h2 class="text-3xl font-bold mb-2">Current Season</h2>
    <p class="text-3xl">{currentSeason}</p>
</div>
