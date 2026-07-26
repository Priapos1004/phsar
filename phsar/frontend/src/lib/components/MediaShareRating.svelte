<script lang="ts">
	/** The media hero's share action — the media-grain twin of AnimeShareRating (see there
	 *  for why this is a wrapper rather than page-level wiring). Shows one rating, with the
	 *  parent anime's name as the card's subtitle. */
	import ShareRatingButton from '$lib/components/ShareRatingButton.svelte';
	import ShareRatingDialog from '$lib/components/ShareRatingDialog.svelte';
	import {
		formatEpisodeCount,
		formatMediaType,
		formatSeason,
		resolveTitle,
		watchStatusLabel,
	} from '$lib/utils/formatString';
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

	let meta = $derived.by(() => {
		const parts = [formatMediaType(media.media_type)];
		const season = formatSeason(media.anime_season_name, media.anime_season_year);
		if (season) parts.push(season);
		if (media.episodes !== null) parts.push(formatEpisodeCount(media.episodes));
		return parts.join(' · ');
	});

	let statusLine = $derived.by(() => {
		if (!rating) return null;
		const parts = [watchStatusLabel(rating.watch_status)];
		if (rating.episodes_watched !== null) {
			parts.push(`${rating.episodes_watched}${media.episodes ? `/${media.episodes}` : ''} eps`);
		}
		if (rating.watched_count > 1) parts.push(`watched ${rating.watched_count}×`);
		return parts.join(' · ');
	});
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
	title={resolveTitle(media.title, media.name_eng, media.name_jap, nameLanguage)}
	subtitle={resolveTitle(media.anime_title, media.anime_name_eng, media.anime_name_jap, nameLanguage)}
	coverUrl={media.cover_image}
	{meta}
	score={rating?.rating ?? null}
	{ratingStep}
	{statusLine}
	ratings={rating ? [rating] : []}
/>
