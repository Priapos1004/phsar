<script lang="ts">
	import * as Card from '$lib/components/ui/card';
	import { Separator } from '$lib/components/ui/separator';
	import * as cls from '$lib/styles/classes';
	import RatingsOverviewStats from '$lib/components/RatingsOverviewStats.svelte';
	import RatingsOverviewTimeline from '$lib/components/RatingsOverviewTimeline.svelte';
	import RatingsOverviewNotes from '$lib/components/RatingsOverviewNotes.svelte';
	import RatingsOverviewAttributes from '$lib/components/RatingsOverviewAttributes.svelte';
	import { RATING_ATTRIBUTE_OPTIONS, getRatingAttr, type AnimeMediaItem, type RatingOut } from '$lib/types/api';

	interface Props {
		ratings: RatingOut[];
		media: AnimeMediaItem[];
		scoreDecimals: number;
		minScoreDecimals: number;
	}

	let { ratings, media, scoreDecimals, minScoreDecimals }: Props = $props();

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

	const ATTR_KEYS = Object.keys(RATING_ATTRIBUTE_OPTIONS);
	let hasAttributes = $derived(
		ratings.some((r) => ATTR_KEYS.some((k) => getRatingAttr(r, k) !== null)),
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

		<Separator />

		<RatingsOverviewTimeline {mediaWithRatings} {minScoreDecimals} />

		{#if hasAttributes}
			<Separator />
			<RatingsOverviewAttributes {ratings} />
		{/if}

		{#if notesInOrder.length > 0}
			<Separator />
			<RatingsOverviewNotes notes={notesInOrder} {scoreDecimals} />
		{/if}
	</Card.Content>
</Card.Root>
