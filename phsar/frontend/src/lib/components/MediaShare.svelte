<script lang="ts">
	/** The media hero's share action — the media-grain twin of AnimeShare (see there for why
	 *  this is a wrapper rather than page-level wiring). */
	import ShareButton from '$lib/components/ShareButton.svelte';
	import ShareDialog from '$lib/components/ShareDialog.svelte';
	import { resolveTitle } from '$lib/utils/formatString';
	import { mediaInfoCard, mediaRatingCard } from '$lib/utils/shareContent';
	import type { MediaDetail, NameLanguage, RatingOut } from '$lib/types/api';

	interface Props {
		media: MediaDetail;
		/** This media's rating, or null when unrated — then the info card is the only one on
		 *  offer, which covers every guest. */
		rating: RatingOut | null;
		ratingStep: number;
		nameLanguage: NameLanguage;
	}

	let { media, rating, ratingStep, nameLanguage }: Props = $props();

	let open = $state(false);

	let title = $derived(resolveTitle(media.title, media.name_eng, media.name_jap, nameLanguage));
	let animeTitle = $derived(
		resolveTitle(media.anime_title, media.anime_name_eng, media.anime_name_jap, nameLanguage),
	);
	// The parent anime's name, unless this media IS the whole anime — a single-season show
	// would otherwise print the same string twice.
	let subtitle = $derived(animeTitle === title ? null : animeTitle);

	let ratingCard = $derived(rating ? mediaRatingCard(media, rating, ratingStep) : null);
	let infoCard = $derived(mediaInfoCard(media));
</script>

<!-- Never disabled, including for an entry behind the spoiler frontier: asking to share is
     asking to see. A frontier gate is also unimplementable here — SpoilerGuard's
     click-to-reveal is its own component state, so the page can't tell a revealed entry from
     a hidden one and the button would never come back. -->
<ShareButton
	tooltip={rating ? 'Share your rating as an image' : 'Share this entry as an image'}
	ariaLabel={rating ? 'Share your rating' : 'Share this entry'}
	onclick={() => (open = true)}
/>

<ShareDialog bind:open {title} {subtitle} noun="entry" rating={ratingCard} info={infoCard} />
