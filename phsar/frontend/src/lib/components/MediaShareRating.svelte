<script lang="ts">
	/** The media hero's share action — the media-grain twin of AnimeShareRating (see there
	 *  for why this is a wrapper rather than page-level wiring). */
	import ShareRatingButton from '$lib/components/ShareRatingButton.svelte';
	import ShareRatingDialog from '$lib/components/ShareRatingDialog.svelte';
	import { resolveTitle } from '$lib/utils/formatString';
	import { mediaShareContent } from '$lib/utils/shareContent';
	import type { MediaDetail, NameLanguage, RatingOut } from '$lib/types/api';

	interface Props {
		media: MediaDetail;
		/** This media's rating, or null when unrated — nothing to share. */
		rating: RatingOut | null;
		ratingStep: number;
		nameLanguage: NameLanguage;
		/** Guests can't rate, so they have nothing to share. */
		restricted?: boolean;
	}

	let { media, rating, ratingStep, nameLanguage, restricted = false }: Props = $props();

	let open = $state(false);

	let title = $derived(resolveTitle(media.title, media.name_eng, media.name_jap, nameLanguage));
	let animeTitle = $derived(
		resolveTitle(media.anime_title, media.anime_name_eng, media.anime_name_jap, nameLanguage),
	);
	// The parent anime's name, unless this media IS the whole anime — a single-season show
	// would otherwise print the same string twice.
	let subtitle = $derived(animeTitle === title ? null : animeTitle);

	// Only reachable with a rating: the button below is disabled without one, and the dialog
	// mounts the card only once opened.
	let content = $derived(rating ? mediaShareContent(media, rating) : null);
</script>

<ShareRatingButton
	tooltip={restricted
		? "Guest accounts can't rate, so there's nothing to share"
		: rating
			? 'Share your rating as an image'
			: 'Rate this first to share your rating'}
	ariaLabel="Share your rating"
	onclick={() => (open = true)}
	disabled={restricted || !rating}
/>

<ShareRatingDialog
	bind:open
	{title}
	{subtitle}
	coverUrl={media.cover_image}
	metaLines={content?.metaLines ?? []}
	statusLine={content?.statusLine ?? null}
	score={rating?.rating ?? null}
	{ratingStep}
	ratings={rating ? [rating] : []}
/>
