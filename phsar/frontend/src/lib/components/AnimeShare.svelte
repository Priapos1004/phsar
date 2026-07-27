<script lang="ts">
	/**
	 * The anime hero's share action: button + dialog + the card's content.
	 *
	 * A per-grain wrapper rather than a dozen props wired up in the page, because the media
	 * page needs the same thing with different inputs — and this repo has a documented
	 * history of the anime and media pages drifting apart whenever they each kept their own
	 * copy (the AttributeSelect / RatingNeighbors / ScoreDial extractions). Mounting one
	 * component also means a page can't wire the button and forget the dialog. The strings
	 * themselves live in `utils/shareContent` so they're pure and testable.
	 */
	import ShareButton from '$lib/components/ShareButton.svelte';
	import ShareDialog from '$lib/components/ShareDialog.svelte';
	import { resolveTitle } from '$lib/utils/formatString';
	import { animeInfoCard, animeRatingCard } from '$lib/utils/shareContent';
	import type { AnimeDetail, NameLanguage, RatingOut } from '$lib/types/api';

	interface Props {
		anime: AnimeDetail;
		/** Every rating the user has for this anime's media. Empty means the info card is the
		 *  only one on offer — which covers every guest, since guests can't rate. */
		ratings: RatingOut[];
		ratingStep: number;
		nameLanguage: NameLanguage;
	}

	let { anime, ratings, ratingStep, nameLanguage }: Props = $props();

	let open = $state(false);
	let hasRating = $derived(ratings.length > 0);
	let rating = $derived(hasRating ? animeRatingCard(anime, ratings, ratingStep) : null);
	let info = $derived(animeInfoCard(anime));
</script>

<!-- Never disabled. Sharing an anime you haven't watched is the point of the info card — it's
     how you tell someone a show looks good — so an unrated anime and a guest account both get
     a live button, they just get the other card. -->
<ShareButton
	tooltip={hasRating ? 'Share your rating as an image' : 'Share this anime as an image'}
	ariaLabel={hasRating ? 'Share your rating' : 'Share this anime'}
	onclick={() => (open = true)}
/>

<!-- No subtitle: an anime's alternate-language name beside its title reads as noise on a
     card whose whole job is to be glanceable. Holds for the one-entry shape too, which
     otherwise matches the media card. -->
<ShareDialog
	bind:open
	title={resolveTitle(anime.title, anime.name_eng, anime.name_jap, nameLanguage)}
	subtitle={null}
	noun="anime"
	{rating}
	{info}
/>
