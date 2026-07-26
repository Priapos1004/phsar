<script lang="ts">
	/**
	 * The anime hero's share action: button + dialog + the strings that land on the card.
	 *
	 * A per-grain wrapper rather than nine props wired up in the page, because the media
	 * page needs the same thing with different inputs — and this repo has a documented
	 * history of the anime and media pages drifting apart whenever they each kept their own
	 * copy (the AttributeSelect / RatingNeighbors / ScoreDial extractions). Mounting one
	 * component also means a page can't wire the button and forget the dialog.
	 */
	import ShareRatingButton from '$lib/components/ShareRatingButton.svelte';
	import ShareRatingDialog from '$lib/components/ShareRatingDialog.svelte';
	import {
		formatEpisodeCount,
		formatSeasonRange,
		resolveSubtitles,
		resolveTitle,
	} from '$lib/utils/formatString';
	import { meanScore } from '$lib/utils/ratingStats';
	import type { AnimeDetail, NameLanguage, RatingOut } from '$lib/types/api';

	interface Props {
		anime: AnimeDetail;
		/** Every rating the user has for this anime's media; empty = nothing to share. */
		ratings: RatingOut[];
		ratingStep: number;
		nameLanguage: NameLanguage;
		/** Guests can't rate, so they have nothing to share. */
		restricted?: boolean;
	}

	let { anime, ratings, ratingStep, nameLanguage, restricted = false }: Props = $props();

	let open = $state(false);
	let hasRating = $derived(ratings.length > 0);

	let meta = $derived.by(() => {
		const parts: string[] = [];
		const season = formatSeasonRange(anime.season_start, anime.season_end);
		if (season) parts.push(season);
		if (anime.total_episodes !== null) parts.push(formatEpisodeCount(anime.total_episodes));
		parts.push(`${anime.media.length} media`);
		return parts.join(' · ');
	});
</script>

<ShareRatingButton
	tooltip={restricted
		? "Guest accounts can't rate, so there's nothing to share"
		: hasRating
			? 'Share your rating as an image'
			: 'Rate this anime first to share your rating'}
	ariaLabel="Share your rating"
	onclick={() => (open = true)}
	disabled={restricted || !hasRating}
/>

<ShareRatingDialog
	bind:open
	title={resolveTitle(anime.title, anime.name_eng, anime.name_jap, nameLanguage)}
	subtitle={resolveSubtitles(anime.title, anime.name_eng, anime.name_jap, nameLanguage)[0] ?? null}
	coverUrl={anime.cover_image}
	{meta}
	score={meanScore(ratings)}
	{ratingStep}
	statusLine={`${ratings.length} of ${anime.media.length} rated`}
	{ratings}
/>
