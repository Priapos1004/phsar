<script lang="ts">
	/**
	 * The anime hero's share action: button + dialog + the card's content.
	 *
	 * A per-grain wrapper rather than nine props wired up in the page, because the media
	 * page needs the same thing with different inputs — and this repo has a documented
	 * history of the anime and media pages drifting apart whenever they each kept their own
	 * copy (the AttributeSelect / RatingNeighbors / ScoreDial extractions). Mounting one
	 * component also means a page can't wire the button and forget the dialog. The strings
	 * themselves live in `utils/shareContent` so they're pure and testable.
	 */
	import ShareRatingButton from '$lib/components/ShareRatingButton.svelte';
	import ShareRatingDialog from '$lib/components/ShareRatingDialog.svelte';
	import { resolveTitle } from '$lib/utils/formatString';
	import { meanScore } from '$lib/utils/ratingStats';
	import { animeShareContent } from '$lib/utils/shareContent';
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
	let content = $derived(animeShareContent(anime, ratings));
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

<!-- No subtitle: an anime's alternate-language name beside its title reads as noise on a
     card whose whole job is to be glanceable. Holds for the one-entry shape too, which
     otherwise matches the media card. -->
<ShareRatingDialog
	bind:open
	title={resolveTitle(anime.title, anime.name_eng, anime.name_jap, nameLanguage)}
	subtitle={null}
	score={meanScore(ratings)}
	{ratingStep}
	{ratings}
	{...content}
/>
