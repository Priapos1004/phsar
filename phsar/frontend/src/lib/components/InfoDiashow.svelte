<script lang="ts">
	import { getCurrentSeason } from '$lib/utils/getSeason';
	import * as Card from '$lib/components/ui/card';

	const currentSeason = getCurrentSeason();
</script>

<Card.Root class="bg-primary text-primary-foreground">
	<Card.Content class="flex flex-col items-center py-6">
	    <h2 class="text-3xl font-bold mb-2">Current Season</h2>
	    <p class="text-3xl">{currentSeason}</p>
	</Card.Content>
</Card.Root>
