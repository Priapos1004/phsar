<script lang="ts">
	/**
	 * Renders a `ShareCard` off-screen, rasterizes it, and shows the resulting PNG.
	 *
	 * The preview is the actual generated image rather than the live card, so what the
	 * user sends is exactly what they approved — the rasterizer's foreignObject pass can
	 * differ subtly from live DOM, and a WYSIWYG preview makes any such difference visible
	 * here instead of in someone's chat. It also makes Save/Share instant.
	 *
	 * Two cards can be on offer for the same title: the rating card and the plain info card.
	 * Each is built at most once per dialog session and kept, so toggling between them swaps
	 * an already-rendered PNG rather than rebuilding it.
	 */
	import { onDestroy, tick, untrack } from 'svelte';
	import { page } from '$app/state';
	import * as Dialog from '$lib/components/ui/dialog';
	import { Button } from '$lib/components/ui/button';
	import { Download, RefreshCw, Share2 } from 'lucide-svelte';
	import ShareCard from '$lib/components/ShareCard.svelte';
	import SegmentedControl from '$lib/components/SegmentedControl.svelte';
	import { getEcharts } from '$lib/echarts';
	import { triggerBlobDownload } from '$lib/utils/download';
	import {
		canShareFiles,
		captureCardPng,
		fetchImageAsDataUri,
		isIosLike,
		shareFile,
		shareFileName,
	} from '$lib/utils/shareImage';
	import { RATING_LABEL, type ShareVariant, type ShareVariantContent } from '$lib/utils/shareContent';

	interface Props {
		open: boolean;
		/** Already resolved to the viewer's name-language setting. */
		title: string;
		subtitle: string | null;
		/** What this title is called in the dialog heading. */
		noun: 'anime' | 'entry';
		/** `null` when the viewer hasn't rated this, which is also when there is nothing to
		 *  toggle between. Guests are simply the case that is always null. */
		rating: ShareVariantContent | null;
		info: ShareVariantContent;
	}

	let { open = $bindable(), title, subtitle, noun, rating, info }: Props = $props();

	/**
	 * Ceiling on waiting for the card to paint. Reachable on the rating card, not just a hang
	 * guard: the radar always renders, so the first share from a page with no other chart
	 * cold-loads the ECharts chunk here. Generous enough that a slow link finishes rather than
	 * capturing a half-drawn radar; if it does fire, the rest of the card is still correct.
	 * The info card has no chart, so reaching this there would be a bug, not a slow link.
	 */
	const CARD_READY_TIMEOUT_MS = 15000;

	let cardEl = $state<HTMLDivElement | null>(null);
	let coverDataUri = $state<string | null>(null);
	let cardMounted = $state(false);
	/** Which variant the off-screen card is rendering — not necessarily the selected one, since
	 *  a switch mid-build leaves the old run to finish and be discarded. */
	let buildingVariant = $state<ShareVariant>('info');
	/** One built PNG per variant. File and object URL are one fact — kept together so no
	 *  condition can see them half-set. */
	let previews = $state<Partial<Record<ShareVariant, { file: File; url: string }>>>({});
	let generating = $state(false);
	/** A share sheet is open. The sheet is an OS surface with no cancellation path, so the
	 *  only honest thing a second click can do is nothing — this is what makes it inert. */
	let sharing = $state(false);
	let error = $state('');

	/** null = the viewer hasn't chosen, so follow whatever this title defaults to. Keeping the
	 *  choice separate from the default is what lets `reset()` forget it in one assignment. */
	let picked = $state<ShareVariant | null>(null);
	let variant = $derived<ShareVariant>(picked ?? (rating ? 'rating' : 'info'));

	/** The assembled card for a variant. One rule, so the card that renders can't disagree with
	 *  the cover that was fetched or the filename that was built. */
	function contentFor(v: ShareVariant): ShareVariantContent {
		return v === 'rating' && rating ? rating : info;
	}

	// Object URLs are otherwise only released when the dialog is closed, and an effect body
	// doesn't run on unmount — so navigating away with the dialog open would strand two
	// full-size PNGs for the life of the SPA.
	onDestroy(reset);

	let building = $derived(contentFor(buildingVariant));
	let preview = $derived(previews[variant] ?? null);
	let canShare = $derived(preview !== null && canShareFiles(preview.file));
	let captureFailed = $derived(!!error && preview === null);
	// On iOS the download path reaches Files, never Photos — so there is no second button to
	// offer, only the sheet. Elsewhere the two actions are genuinely different.
	let sheetOnly = $derived(canShare && isIosLike());

	let cardReadyResolve: (() => void) | null = null;
	// De-races overlapping generations (reopen, retry, a variant switch mid-build): a stale run
	// must not publish its preview or tear down the live run's off-screen card. Same idiom as
	// the detail pages' loadRequestId.
	let generationId = 0;
	/** Cover data URIs by source URL. The two variants can want different covers (a one-entry
	 *  anime borrows its member's), so a toggle shouldn't re-download either of them. */
	const coverCache = new Map<string, string | null>();

	// `untrack` so this depends on `open` and `variant` ALONE. generate()/reset() both read and
	// write `previews`, which without it makes the effect re-trigger on its own output — an
	// endless rebuild loop.
	$effect(() => {
		const isOpen = open;
		const v = variant;
		untrack(() => {
			if (!isOpen) {
				reset();
				return;
			}
			error = ''; // a failure on the other variant isn't this one's
			if (!previews[v]) void generate(v);
		});
	});

	function handleCardReady() {
		cardReadyResolve?.();
		cardReadyResolve = null;
	}

	function releasePreviews() {
		for (const built of Object.values(previews)) URL.revokeObjectURL(built.url);
		previews = {};
	}

	function reset() {
		generationId++; // abandon any in-flight run so closing mid-build publishes nothing
		releasePreviews();
		coverCache.clear(); // bounded to one dialog session, which is all the toggle needs
		cardMounted = false;
		coverDataUri = null;
		error = '';
		// Cleared here too: a platform that never settles its share promise would otherwise
		// leave the button inert for good.
		sharing = false;
		picked = null;
	}

	async function readCover(url: string | null): Promise<string | null> {
		if (!url) return null;
		const cached = coverCache.get(url);
		if (cached !== undefined) return cached;
		const data = await fetchImageAsDataUri(url);
		coverCache.set(url, data);
		return data;
	}

	async function generate(v: ShareVariant) {
		const thisRun = ++generationId;
		buildingVariant = v;
		generating = true;
		error = '';
		let timer: ReturnType<typeof setTimeout> | undefined;

		try {
			const source = contentFor(v);
			const needsChart = v === 'rating';
			// Warm the chart bundle without awaiting it: it's the long pole on a first share.
			// The catch keeps a failed chunk load (deploy skew) from surfacing as an unhandled
			// rejection — the radar's own path already rides it out via the card-ready timeout.
			if (needsChart) void getEcharts().catch(() => {});

			// A fresh card instance per build. Both readiness signals fire once per mount — the
			// radar's paint event, and the info card's own — so re-rendering the existing
			// instance across a variant switch would leave the capture waiting on a signal that
			// never comes again.
			cardMounted = false;
			await tick();
			if (thisRun !== generationId) return;

			const cardReady = new Promise<void>((resolve) => {
				cardReadyResolve = resolve;
				timer = setTimeout(resolve, CARD_READY_TIMEOUT_MS);
			});

			// With a chart, mount without awaiting the cover — the two have nothing to say to
			// each other, and the cover only has to be in the DOM by capture time. Without one
			// there is no long pole to overlap, so settling the cover first makes card-ready
			// mean exactly "everything this card draws is painted".
			//
			// Both branches re-check staleness BEFORE publishing: the two variants can want
			// different covers (a one-entry anime borrows its member's), so an abandoned run
			// resolving late must not write its cover into the live run's card.
			if (!needsChart) {
				const cover = await readCover(source.coverUrl);
				if (thisRun !== generationId) return;
				coverDataUri = cover;
			}

			cardMounted = true;
			await tick();
			if (needsChart) {
				const cover = await readCover(source.coverUrl);
				if (thisRun !== generationId) return;
				coverDataUri = cover;
			}
			await cardReady;
			await tick();
			if (thisRun !== generationId) return;

			if (!cardEl) throw new Error('Share card did not mount');
			const blob = await captureCardPng(cardEl);
			if (thisRun !== generationId) return;

			const file = new File([blob], shareFileName(title, v), { type: 'image/png' });
			previews[v] = { file, url: URL.createObjectURL(file) };
		} catch (err) {
			if (thisRun !== generationId) return;
			// Surface the cause for debugging; the user gets the friendly line + Try again.
			console.error('Share card capture failed', err);
			error = "Couldn't build the image.";
		} finally {
			clearTimeout(timer);
			if (thisRun === generationId) {
				// The off-screen copy has served its purpose — unmount it so its chart
				// instance is disposed instead of lingering behind the dialog.
				cardMounted = false;
				cardReadyResolve = null;
				generating = false;
			}
		}
	}

	function handleDownload() {
		if (preview) triggerBlobDownload(preview.file, preview.file.name);
	}

	async function handleShare() {
		if (!preview || sharing) return; // what a second click while the sheet is up lands on
		sharing = true;
		error = '';
		try {
			await shareFile(preview.file, title);
		} catch {
			// On iOS the Save button is collapsed into this one, so "save instead" would
			// point at a button that doesn't exist there.
			error = sheetOnly
				? "Couldn't open the share sheet — try again."
				: "Couldn't open the share sheet — save the image instead.";
		} finally {
			sharing = false;
		}
	}

</script>

<Dialog.Root bind:open>
	<Dialog.Content class="sm:max-w-md">
		<Dialog.Header>
			<Dialog.Title>
				{variant === 'rating' ? 'Share your rating' : `Share this ${noun}`}
			</Dialog.Title>
			<Dialog.Description class="truncate text-muted-foreground">{title}</Dialog.Description>
		</Dialog.Header>

		<div class="space-y-4 py-2">
			<!-- Offered only when there is a rating to choose between: without one the info card
			     isn't an alternative, it's the only card. -->
			{#if rating}
				<div class="flex justify-center">
					<SegmentedControl
						options={[
							{ value: 'rating', label: RATING_LABEL },
							{ value: 'info', label: `Just the ${noun}` },
						]}
						value={variant}
						onSelect={(v) => (picked = v)}
						size="md"
						ariaLabel="Which card to share"
					/>
				</div>
			{/if}

			<div class="flex min-h-[280px] items-center justify-center rounded-xl bg-muted/40 p-2">
				{#if preview}
					<img
						src={preview.url}
						alt="Preview of the shareable card"
						class="max-h-[55vh] w-auto rounded-lg shadow-lg"
					/>
				{:else if generating}
					<span class="animate-pulse text-sm text-muted-foreground">Building your image…</span>
				{/if}
			</div>

			{#if error}
				<p class="text-sm text-destructive">{error}</p>
			{/if}

			<div class="flex gap-2">
				{#if captureFailed}
					<Button class="flex-1" onclick={() => generate(variant)}>
						<RefreshCw class="mr-1.5 size-4" /> Try again
					</Button>
				{:else if sheetOnly}
					<!-- One button, because on iOS both outcomes live behind the same sheet:
					     "Save Image" reaches Photos, any app entry sends it. -->
					<Button class="flex-1" onclick={handleShare} disabled={sharing}>
						<Share2 class="mr-1.5 size-4" /> {sharing ? 'Sharing…' : 'Save or share'}
					</Button>
				{:else}
					<Button class="flex-1" onclick={handleDownload} disabled={!preview}>
						<Download class="mr-1.5 size-4" /> Save image
					</Button>
					{#if canShare}
						<Button variant="secondary" onclick={handleShare} disabled={sharing}>
							<Share2 class="mr-1.5 size-4" /> {sharing ? 'Sharing…' : 'Share'}
						</Button>
					{/if}
				{/if}
			</div>

			<!-- Only the how-to-save sentence is platform-specific; the privacy promise is a
			     standing line with one home, so a reword can't land in just one branch. -->
			<p class="text-sm text-muted-foreground">
				{#if sheetOnly}
					Pick "Save Image" to add it to your Photos, or an app to send it straight away.
				{:else}
					Saved as a picture, so you can send it in any messenger.
				{/if}
				Nothing is published online.
			</p>
		</div>
	</Dialog.Content>
</Dialog.Root>

{#if cardMounted}
	<!-- Off-screen but genuinely laid out: the chart measures its container before it
	     paints, so display:none / visibility:hidden would capture blank. The inner div is
	     the capture target — an unstyled box, so this wrapper's own positioning can't leak
	     into the clone and shift the content out of frame. -->
	<div class="pointer-events-none fixed top-0 left-[-10000px]" aria-hidden="true">
		<div bind:this={cardEl}>
			<ShareCard
				{title}
				{subtitle}
				{coverDataUri}
				metaLines={building.metaLines}
				badges={building.badges}
				headerLabel={building.headerLabel}
				body={building.body}
				host={page.url.host}
				onReady={handleCardReady}
			/>
		</div>
	</div>
{/if}
