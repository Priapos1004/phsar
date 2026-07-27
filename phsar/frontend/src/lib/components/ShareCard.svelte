<script lang="ts">
	/**
	 * The composition rasterized into a shared PNG (see `utils/shareImage.ts`).
	 *
	 * It is the app's own visual sandwich — themed page gradient behind a white elevated
	 * card — because that is what lets `AttributeRadar` and `AttributeBadges` render here
	 * unchanged: their colors are already tuned for the white surface, so the card and the
	 * on-page Attribute Summary stay one implementation.
	 *
	 * Two variants share one shell. The frame (gradient, brand header, cover, title, meta
	 * lines, footer) is identical by construction rather than by discipline, so the rating
	 * export and the info export can never drift into looking like two different products.
	 * `body` is a discriminated union: the fields of the variant you aren't rendering are not
	 * merely unused, they're absent.
	 *
	 * Purely presentational, so the anime grain (aggregated across rated media) and the
	 * media grain (one entry) differ only in what the caller passes.
	 *
	 * Constrained to the CSS the rasterizer's foreignObject pass reproduces faithfully:
	 * no `backdrop-filter`, no CSS `mask`, no scroll containers, and nothing whose layout
	 * depends on the viewport (hence `AttributeBadges layout="wrap"` — see that prop).
	 */
	import { onMount, tick } from 'svelte';
	import AttributeRadar from '$lib/components/AttributeRadar.svelte';
	import AttributeBadges from '$lib/components/AttributeBadges.svelte';
	import * as cls from '$lib/styles/classes';
	import { formatScoreWithStep, formatShortDate } from '$lib/utils/formatString';
	import { SHARE_CARD_HEIGHT, SHARE_CARD_WIDTH } from '$lib/utils/shareImage';
	import type { ShareBadge, ShareBadgeTone, ShareCardBody } from '$lib/utils/shareContent';

	interface Props {
		/** Already resolved to the viewer's name-language setting. */
		title: string;
		/** Second title, or the parent anime's name at media grain. */
		subtitle: string | null;
		/** Cover as a data URI — a remote URL would leave the capture doing network I/O. */
		coverDataUri: string | null;
		/**
		 * Catalog facts, one entry per rendered line. Split by the caller rather than wrapped
		 * here, because only it knows when a line has grown too long (an anime spanning
		 * several seasons carries a full "Fall 2020 - Winter 2026" range).
		 */
		metaLines: string[];
		/** Airing state under the title. Empty on the rating variant, which spends that room
		 *  on the score instead. */
		badges?: ShareBadge[];
		/** Top-right of the brand header — what this card is. */
		headerLabel: string;
		body: ShareCardBody;
		/** The site's host — a prop rather than read here, so the card stays pure. */
		host: string;
		/** Fires once the card has drawn everything it will draw — the signal the capture
		 *  waits on. The rating variant forwards it from the radar; the info variant has no
		 *  chart and raises it itself (see below). */
		onReady?: () => void;
	}

	let {
		title,
		subtitle,
		coverDataUri,
		metaLines,
		badges = [],
		headerLabel,
		body,
		host,
		onReady,
	}: Props = $props();

	// The info variant carries a badge row the rating variant doesn't, and the hero column
	// only has the cover's 176px to spend — at text-xl the worst case (2-line title + 2 badge
	// rows + 3 meta lines) lands half a pixel from clipping. So it steps down unconditionally
	// rather than only for long titles.
	let titleSize = $derived(body.kind === 'info' || title.length > 44 ? 'text-lg' : 'text-xl');
	const dateLabel = formatShortDate(new Date().toISOString());

	const chip = 'rounded-md px-2.5 py-0.5 text-sm font-medium';
	/** Solid tints only — `bg-muted` rather than the page's `bg-card-foreground/8`, because a
	 *  fractional-alpha `color-mix` that fails to reparse in the clone degrades to invisible
	 *  on a light-on-light chip. */
	const studioChip = `${chip} border border-border bg-muted text-card-foreground`;
	/** Tone → the app's shared badge tokens. The tone union is a share-feature concept, so the
	 *  mapping lives here while the tints stay in `classes.ts` with their siblings. */
	const TONE: Record<ShareBadgeTone, string> = {
		airing: cls.badgeAiring,
		unaired: cls.badgeUnaired,
		upcoming: cls.badgeUpcoming,
		finished: cls.badgeFinished,
		complete: cls.badgeComplete,
	};

	let coverImg = $state<HTMLImageElement | null>(null);

	/**
	 * Readiness for the chartless variant.
	 *
	 * "Mounted" is not the signal — the capture needs painted pixels. On the rating variant
	 * the radar's own paint event bought the cover hundreds of milliseconds of decode time
	 * for free; remove the chart and that accidental buffer goes with it, so the decode is
	 * awaited explicitly. `onMount` rather than an `$effect` so it runs once by construction
	 * and `onReady` never joins a dependency set (the same reasoning behind `EChart`
	 * registering its `finished` handler outside the option effect).
	 */
	onMount(() => {
		if (body.kind !== 'info') return; // the radar owns the signal for the rating variant
		void (async () => {
			await tick(); // Svelte's DOM writes are flushed
			await coverImg?.decode().catch(() => {}); // a corrupt cover must not hang the capture
			await new Promise(requestAnimationFrame); // style + layout have run
			onReady?.();
		})();
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
		<span class="text-sm text-white/70">{headerLabel}</span>
	</div>

	<div class="mx-5 flex flex-1 flex-col gap-3 rounded-2xl bg-card p-4">
		<div class="flex shrink-0 gap-4">
			{#if coverDataUri}
				<img
					bind:this={coverImg}
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
				     that keeps a runaway title from squeezing the block below. -->
				<h1
					class="line-clamp-2 max-h-[52px] overflow-hidden font-bold text-card-foreground {titleSize} leading-tight"
				>
					{title}
				</h1>
				{#if subtitle}
					<p class="truncate text-sm text-muted-foreground">{subtitle}</p>
				{/if}
				{#if badges.length}
					<!-- py-0.5, not the hero page's py-1: two badge rows at the taller size
					     overrun the cover's 176px and clip. -->
					<div class="mt-1.5 flex flex-wrap gap-1.5">
						{#each badges as badge}
							<span class="{chip} border {TONE[badge.tone]}">{badge.label}</span>
						{/each}
					</div>
				{/if}
				<div class="mt-1 text-sm text-muted-foreground">
					{#each metaLines as line}
						<p>{line}</p>
					{/each}
				</div>

				{#if body.kind === 'rating'}
					<div class="mt-auto flex items-center gap-3">
						<div class="size-16 {cls.scoreCircle}">
							<span class="text-xl font-bold text-card-foreground">
								{formatScoreWithStep(body.score, body.ratingStep)}
							</span>
						</div>
						{#if body.statusLine}
							<span class="text-sm text-muted-foreground">{body.statusLine}</span>
						{/if}
					</div>
				{/if}
			</div>
		</div>

		{#if body.kind === 'rating'}
			<!-- No gate, unlike the page's Attribute Summary: an image travels without the app
			     around it, so a missing axis would be indistinguishable from one that doesn't
			     exist. Unrated axes and pills render greyed. -->
			<div class="flex flex-1 flex-col justify-center gap-2">
				<AttributeRadar ratings={body.ratings} {onReady} />
				<AttributeBadges ratings={body.ratings} layout="wrap" />
			</div>
		{:else}
			<!-- Facts band across the card's full width rather than beside the cover: in the
			     328px hero column a heavily-tagged anime wraps to four chip rows and pushes the
			     synopsis out of frame. The max-height sits on the CHIPS, not the band, so if a
			     cap is ever relaxed the overflow eats genre chips and the studio row survives.
			     These are plain spans rather than GenreBadges/StudioLinks: those mount a
			     tooltip provider per chip, fetch genre descriptions on mount (network I/O
			     inside the capture window), and render focusable buttons inside an aria-hidden
			     subtree — all three are page affordances a static image has no use for. -->
			<div class="shrink-0 space-y-2">
				<div class="flex max-h-[83px] flex-wrap gap-1.5 overflow-hidden">
					{#each body.genres as genre}
						<span class="{chip} {cls.badgeGenreColor}">{genre}</span>
					{/each}
					<!-- The page's orange, not the theme tint the genres use: an age rating is a
					     different kind of fact, and in one hue it just reads as another genre. -->
					<span class="{chip} {cls.badgeAgeRatingColor}">{body.ageRating}</span>
				</div>
				<div class="flex flex-wrap items-center gap-x-2 gap-y-1.5">
					<span class="text-sm font-medium text-muted-foreground">Studio</span>
					{#each body.studios as studio}
						<span class={studioChip}>{studio}</span>
					{/each}
				</div>
			</div>

			<!-- min-h-0 is load-bearing: a flex child defaults to min-height:auto, which defeats
			     overflow-hidden and lets a long synopsis bleed past the white card and clip the
			     footer.

			     The clamp is sized to the WORST band, not the common one: the heaviest catalog
			     rows wrap their chips to two rows (~90px), leaving ~245px here, and 12 lines is
			     234px. Clamping any looser would fill the common one-chip-row card (~276px)
			     but let this div silently cut the heavy ones mid-word — the clamp's ellipsis
			     has to be what trims the text, never the overflow. -->
			<div class="min-h-0 flex-1 overflow-hidden">
				<p class="line-clamp-12 text-sm break-words text-card-foreground">
					{body.synopsis ?? 'No synopsis on record.'}
				</p>
			</div>
		{/if}
	</div>

	<div class="flex items-center justify-between px-6 py-3 text-sm text-white/60">
		<span>{host}</span>
		<span>{dateLabel}</span>
	</div>
</div>
