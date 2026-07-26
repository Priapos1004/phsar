<script lang="ts">
	/**
	 * The composition rasterized into a shared rating PNG (see `utils/shareImage.ts`).
	 *
	 * It is the app's own visual sandwich — themed page gradient behind a white elevated
	 * card — because that is what lets `AttributeRadar` and `AttributeBadges` render here
	 * unchanged: their colors are already tuned for the white surface, so the card and the
	 * on-page Attribute Summary stay one implementation.
	 *
	 * Purely presentational, so the anime grain (aggregated across rated media) and the
	 * media grain (one rating) differ only in what the caller passes.
	 *
	 * Constrained to the CSS the rasterizer's foreignObject pass reproduces faithfully:
	 * no `backdrop-filter`, no CSS `mask`, no scroll containers, and nothing whose layout
	 * depends on the viewport (hence `AttributeBadges layout="wrap"` — see that prop).
	 */
	import AttributeRadar from '$lib/components/AttributeRadar.svelte';
	import AttributeBadges from '$lib/components/AttributeBadges.svelte';
	import * as cls from '$lib/styles/classes';
	import { hasAnyAttribute } from '$lib/utils/ratingAttributes';
	import { formatScoreWithStep, formatShortDate } from '$lib/utils/formatString';
	import { SHARE_CARD_HEIGHT, SHARE_CARD_WIDTH } from '$lib/utils/shareImage';
	import type { RatingOut } from '$lib/types/api';

	interface Props {
		/** Already resolved to the viewer's name-language setting. */
		title: string;
		/** Second title, or the parent anime's name at media grain. */
		subtitle: string | null;
		/** Cover as a data URI — a remote URL would leave the capture doing network I/O. */
		coverDataUri: string | null;
		/** Catalog line, e.g. "TV · Fall 2019 · 24 eps". */
		meta: string;
		score: number | null;
		ratingStep: number;
		/** Watch context, e.g. "Completed · watched 2×" or "3 of 4 entries rated". */
		statusLine: string | null;
		/** N ratings at anime grain, exactly one at media grain — feeds radar + pills. */
		ratings: RatingOut[];
		/** The site's host — a prop rather than read here, so the card stays pure. */
		host: string;
		/**
		 * Fires once the card has drawn everything it is going to draw — the signal the
		 * capture waits on. Total by construction: forwarded from the radar when there is
		 * one, fired directly when the attribute block is omitted entirely, so the caller's
		 * timeout stays a hang guard rather than a routine wait.
		 */
		onReady?: () => void;
	}

	let {
		title,
		subtitle,
		coverDataUri,
		meta,
		score,
		ratingStep,
		statusLine,
		ratings,
		host,
		onReady,
	}: Props = $props();

	let showAttributes = $derived(hasAnyAttribute(ratings));
	// Long titles step down a size rather than losing a whole word to the 2-line clamp.
	let titleSize = $derived(title.length > 44 ? 'text-lg' : 'text-xl');
	const dateLabel = formatShortDate(new Date().toISOString());

	$effect(() => {
		// No attribute block → no radar to wait on, so the card is already done.
		if (!showAttributes) onReady?.();
	});
</script>

<div
	class="flex flex-col overflow-hidden font-sans text-white"
	style="width: {SHARE_CARD_WIDTH}px; height: {SHARE_CARD_HEIGHT}px;
	       background-color: var(--gradient-to);
	       background-image: linear-gradient(to bottom right, var(--gradient-from), var(--gradient-via), var(--gradient-to));"
>
	<div class="flex items-center justify-between px-6 pt-5 pb-4">
		<div class="flex items-center gap-2">
			<!-- The 32px favicon, not the full logo: the rasterizer re-embeds every non-data
			     `<img>` src as base64 on each capture, and the logo is 132 KB for a 28px mark. -->
			<img src="/favicon-32x32.png" alt="" class="size-7" />
			<span class="text-xl font-bold tracking-widest">PHSAR</span>
		</div>
		<span class="text-sm text-white/70">My rating</span>
	</div>

	<div class="mx-5 flex flex-1 flex-col gap-3 rounded-2xl bg-card p-4">
		<div class="flex gap-4">
			{#if coverDataUri}
				<img
					src={coverDataUri}
					alt=""
					class="h-[176px] w-[124px] shrink-0 rounded-lg object-cover ring-1 ring-border"
				/>
			{:else}
				<div
					class="flex h-[176px] w-[124px] shrink-0 items-center justify-center rounded-lg bg-muted text-sm text-muted-foreground italic"
				>
					No image
				</div>
			{/if}

			<div class="flex min-w-0 flex-1 flex-col">
				<!-- line-clamp gives the ellipsis; the height cap is the structural backstop
				     that keeps a runaway title from squeezing the attribute block below. -->
				<h1
					class="line-clamp-2 max-h-[52px] overflow-hidden font-bold text-card-foreground {titleSize} leading-tight"
				>
					{title}
				</h1>
				{#if subtitle}
					<p class="truncate text-sm text-muted-foreground">{subtitle}</p>
				{/if}
				<p class="mt-1 text-sm text-muted-foreground">{meta}</p>

				<div class="mt-auto flex items-center gap-3">
					{#if score !== null}
						<div class="size-16 {cls.scoreCircle}">
							<span class="text-xl font-bold text-card-foreground">
								{formatScoreWithStep(score, ratingStep)}
							</span>
						</div>
					{/if}
					{#if statusLine}
						<span class="text-sm text-muted-foreground">{statusLine}</span>
					{/if}
				</div>
			</div>
		</div>

		{#if showAttributes}
			<div class="flex flex-1 flex-col justify-center gap-2">
				<AttributeRadar {ratings} {onReady} />
				<AttributeBadges {ratings} layout="wrap" />
			</div>
		{/if}
	</div>

	<div class="flex items-center justify-between px-6 py-3 text-sm text-white/60">
		<span>{host}</span>
		<span>{dateLabel}</span>
	</div>
</div>
