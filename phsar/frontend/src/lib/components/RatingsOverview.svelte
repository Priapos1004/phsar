<script lang="ts">
	import * as Card from '$lib/components/ui/card';
	import * as cls from '$lib/styles/classes';
	import RatingsOverviewStats from '$lib/components/RatingsOverviewStats.svelte';
	import RatingsOverviewTimeline from '$lib/components/RatingsOverviewTimeline.svelte';
	import RatingsOverviewNotes from '$lib/components/RatingsOverviewNotes.svelte';
	import RatingsOverviewAttributes from '$lib/components/RatingsOverviewAttributes.svelte';
	import type { AnimeMediaItem, RatingOut } from '$lib/types/api';

	interface Props {
		ratings: RatingOut[];
		media: AnimeMediaItem[];
	}

	let { ratings, media }: Props = $props();

	let ratingsMap = $derived(new Map(ratings.map((r) => [r.media_uuid, r])));

	let mediaWithRatings = $derived(
		media.map((m) => ({
			media: m,
			rating: ratingsMap.get(m.uuid) ?? null,
		})),
	);

	let avgScore = $derived(
		ratings.length > 0 ? ratings.reduce((sum, r) => sum + r.rating, 0) / ratings.length : 0,
	);
	let droppedCount = $derived(ratings.filter((r) => r.dropped).length);

	let totalEpisodesWatched = $derived(
		ratings.reduce((sum, r) => sum + (r.episodes_watched ?? 0), 0),
	);

	// All media, not just rated ones
	let totalEpisodesAvailable = $derived(
		media.reduce((sum, m) => sum + (m.episodes ?? 0), 0),
	);

	let notesInOrder = $derived(
		mediaWithRatings
			.filter((mr) => mr.rating?.note)
			.map((mr) => ({
				title: mr.media.name_eng ?? mr.media.title,
				note: mr.rating!.note!,
				rating: mr.rating!.rating,
			})),
	);
</script>

<Card.Root class={cls.cardGlass}>
	<Card.Content class="space-y-6">
		<h2 class="text-lg font-semibold text-card-foreground">Your Ratings</h2>

		<RatingsOverviewStats
			{avgScore}
			ratedCount={ratings.length}
			totalCount={media.length}
			{droppedCount}
			{totalEpisodesWatched}
			{totalEpisodesAvailable}
		/>

		<RatingsOverviewTimeline {mediaWithRatings} />

		<RatingsOverviewAttributes {ratings} />

		{#if notesInOrder.length > 0}
			<RatingsOverviewNotes notes={notesInOrder} />
		{/if}
	</Card.Content>
</Card.Root>
