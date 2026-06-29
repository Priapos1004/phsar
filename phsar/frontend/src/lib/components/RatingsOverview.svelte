<script lang="ts">
	import * as Card from '$lib/components/ui/card';
	import { Separator } from '$lib/components/ui/separator';
	import * as cls from '$lib/styles/classes';
	import RatingsOverviewStats from '$lib/components/RatingsOverviewStats.svelte';
	import RatingsOverviewTimeline from '$lib/components/RatingsOverviewTimeline.svelte';
	import RatingsOverviewNotes from '$lib/components/RatingsOverviewNotes.svelte';
	import RatingsOverviewAttributes from '$lib/components/RatingsOverviewAttributes.svelte';
	import { resolveTitle } from '$lib/utils/formatString';
	import { episodesWatchedOf } from '$lib/utils/ratingStats';
	import { userSettings } from '$lib/stores/userSettings';
	import { RATING_ATTRIBUTE_OPTIONS, getRatingAttr, isAttrRated, type AnimeMediaItem, type RatingOut } from '$lib/types/api';

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
	let droppedCount = $derived(ratings.filter((r) => r.watch_status === 'dropped').length);
	let onHoldCount = $derived(ratings.filter((r) => r.watch_status === 'on_hold').length);

	let totalEpisodesWatched = $derived(
		mediaWithRatings.reduce(
			(sum, { media: m, rating: r }) =>
				r ? sum + episodesWatchedOf(r.episodes_watched, r.watch_status, m.episodes) : sum,
			0,
		),
	);

	// All media, not just rated ones
	let totalEpisodesAvailable = $derived(
		media.reduce((sum, m) => sum + (m.episodes ?? 0), 0),
	);

	// The aggregate denominator (Σ episodes) is only meaningful when every rated media has
	// a known episode total. If a watched media has no total (a still-airing series), it's
	// in the numerator but not the denominator, so "100 / 108" pits a watched count against
	// an unrelated total — in that case the stat shows only the watched count.
	let episodeTotalKnown = $derived(
		mediaWithRatings.every(({ media: m, rating: r }) => !r || m.episodes != null),
	);

	let nameLanguage = $derived($userSettings?.name_language ?? 'english');

	let notesInOrder = $derived(
		mediaWithRatings
			.filter((mr) => mr.rating?.note)
			.map((mr) => ({
				title: resolveTitle(mr.media.title, mr.media.name_eng, mr.media.name_jap, nameLanguage),
				note: mr.rating!.note!,
				rating: mr.rating!.rating,
			})),
	);

	const ATTR_KEYS = Object.keys(RATING_ATTRIBUTE_OPTIONS);
	// A rating carrying only the auto-set not_applicable ending doesn't count as
	// having attributes, so it can't trigger an empty Attribute Summary section.
	let hasAttributes = $derived(
		ratings.some((r) => ATTR_KEYS.some((k) => isAttrRated(getRatingAttr(r, k)))),
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
			{onHoldCount}
			{totalEpisodesWatched}
			{totalEpisodesAvailable}
			{episodeTotalKnown}
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
