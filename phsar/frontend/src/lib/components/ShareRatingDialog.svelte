<script lang="ts">
	/**
	 * Renders a `ShareCard` off-screen, rasterizes it, and shows the resulting PNG.
	 *
	 * The preview is the actual generated image rather than the live card, so what the
	 * user sends is exactly what they approved — the rasterizer's foreignObject pass can
	 * differ subtly from live DOM, and a WYSIWYG preview makes any such difference visible
	 * here instead of in someone's chat. It also makes Save/Share instant.
	 */
	import { tick, untrack } from 'svelte';
	import { page } from '$app/state';
	import * as Dialog from '$lib/components/ui/dialog';
	import { Button } from '$lib/components/ui/button';
	import { Download, RefreshCw, Share2 } from 'lucide-svelte';
	import ShareCard from '$lib/components/ShareCard.svelte';
	import { triggerBlobDownload } from '$lib/utils/download';
	import {
		canShareFiles,
		captureCardPng,
		fetchImageAsDataUri,
		shareFile,
		shareFileName,
	} from '$lib/utils/shareImage';
	import type { RatingOut } from '$lib/types/api';

	interface Props {
		open: boolean;
		/** Already resolved to the viewer's name-language setting. */
		title: string;
		subtitle: string | null;
		coverUrl: string | null;
		meta: string;
		score: number | null;
		ratingStep: number;
		statusLine: string | null;
		ratings: RatingOut[];
	}

	let {
		open = $bindable(),
		title,
		subtitle,
		coverUrl,
		meta,
		score,
		ratingStep,
		statusLine,
		ratings,
	}: Props = $props();

	/** Hang guard only: `ShareCard.onReady` is total, so this should never fire. */
	const CARD_READY_TIMEOUT_MS = 5000;

	let cardEl = $state<HTMLDivElement | null>(null);
	let coverDataUri = $state<string | null>(null);
	let cardMounted = $state(false);
	/** File and object URL are one fact — kept together so no condition can see them half-set. */
	let preview = $state<{ file: File; url: string } | null>(null);
	let generating = $state(false);
	let error = $state('');

	let cardReadyResolve: (() => void) | null = null;
	// De-races overlapping generations (reopen, retry): a stale run must not publish its
	// preview or tear down the live run's off-screen card. Same idiom as the detail pages'
	// loadRequestId.
	let generationId = 0;

	let canShare = $derived(preview !== null && canShareFiles(preview.file));
	let captureFailed = $derived(!!error && preview === null);

	// `untrack` so this depends on `open` ALONE. generate()/reset() both read and write
	// `preview`, which without it makes the effect re-trigger on its own output — an
	// endless rebuild loop.
	$effect(() => {
		const isOpen = open;
		untrack(() => {
			if (isOpen) void generate();
			else reset();
		});
	});

	function handleCardReady() {
		cardReadyResolve?.();
		cardReadyResolve = null;
	}

	function releasePreview() {
		if (preview) URL.revokeObjectURL(preview.url);
		preview = null;
	}

	function reset() {
		generationId++; // abandon any in-flight run so closing mid-build publishes nothing
		releasePreview();
		cardMounted = false;
		coverDataUri = null;
		error = '';
	}

	async function generate() {
		const thisRun = ++generationId;
		generating = true;
		error = '';
		releasePreview();
		let timer: ReturnType<typeof setTimeout> | undefined;

		try {
			// Start the cover read, then mount straight away rather than awaiting it: the
			// card's chart pulls a large chunk on first use, and the two have nothing to say
			// to each other. The cover only has to be in the DOM by capture time.
			const cover = coverUrl ? fetchImageAsDataUri(coverUrl) : Promise.resolve(null);

			const cardReady = new Promise<void>((resolve) => {
				cardReadyResolve = resolve;
				timer = setTimeout(resolve, CARD_READY_TIMEOUT_MS);
			});

			cardMounted = true;
			await tick();
			coverDataUri = await cover;
			await cardReady;
			await tick();
			if (thisRun !== generationId) return;

			if (!cardEl) throw new Error('Share card did not mount');
			const blob = await captureCardPng(cardEl);
			if (thisRun !== generationId) return;

			const file = new File([blob], shareFileName(title), { type: 'image/png' });
			preview = { file, url: URL.createObjectURL(file) };
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
		if (!preview) return;
		try {
			await shareFile(preview.file, title);
		} catch {
			error = "Couldn't open the share sheet — save the image instead.";
		}
	}
</script>

<Dialog.Root bind:open>
	<Dialog.Content class="sm:max-w-md">
		<Dialog.Header>
			<Dialog.Title>Share your rating</Dialog.Title>
			<Dialog.Description class="truncate text-muted-foreground">{title}</Dialog.Description>
		</Dialog.Header>

		<div class="space-y-4 py-2">
			<div class="flex min-h-[280px] items-center justify-center rounded-xl bg-muted/40 p-2">
				{#if preview}
					<img
						src={preview.url}
						alt="Preview of your shareable rating card"
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
					<Button class="flex-1" onclick={() => generate()}>
						<RefreshCw class="mr-1.5 size-4" /> Try again
					</Button>
				{:else}
					<Button class="flex-1" onclick={handleDownload} disabled={!preview}>
						<Download class="mr-1.5 size-4" /> Save image
					</Button>
					{#if canShare}
						<Button variant="secondary" onclick={handleShare}>
							<Share2 class="mr-1.5 size-4" /> Share
						</Button>
					{/if}
				{/if}
			</div>

			<p class="text-sm text-muted-foreground">
				Saved as a picture, so you can send it in any messenger. Nothing is published online.
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
				{meta}
				{score}
				{ratingStep}
				{statusLine}
				{ratings}
				host={page.url.host}
				onReady={handleCardReady}
			/>
		</div>
	</div>
{/if}
