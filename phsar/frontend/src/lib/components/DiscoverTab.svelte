<script lang="ts">
	// Discover: spin the wheel for today's world, then that world's rows
	// (docs/features/browse.md). Before the spin the tab wears the user's theme; after it the
	// world's colour stands in for `--primary` inside this tab only, so the navbar and the
	// tab bar above keep the theme and switching tabs never changes the page's mood.
	import { getContext, onMount } from 'svelte';
	import { ApiError } from '$lib/api';
	import BrowsePageRows from '$lib/components/BrowsePageRows.svelte';
	import DiscoverWheel from '$lib/components/DiscoverWheel.svelte';
	import WorldParticles from '$lib/components/WorldParticles.svelte';
	import { discoverWorlds, spinWorld, type DiscoverState } from '$lib/stores/browseRows';
	import { worldLook } from '$lib/utils/discoverWorlds';

	const getUserRole = getContext<() => string | null>('userRole');
	let isGuest = $derived(getUserRole?.() === 'restricted_user');

	let discover = $state<DiscoverState | null>(null);
	let loadError = $state('');
	let spinError = $state('');
	let spinning = $state(false);
	// Set by a spin in this visit, so only a fresh draw plays the reveal — not a return.
	let revealed = $state(false);
	let wheel = $state<ReturnType<typeof DiscoverWheel>>();

	onMount(async () => {
		try {
			discover = await discoverWorlds(isGuest);
		} catch (e) {
			loadError = e instanceof ApiError ? e.detail : 'Discover could not load. Reload the page to try again.';
		}
	});

	async function spin() {
		if (!discover || spinning) return;
		spinning = true;
		spinError = '';
		try {
			const spun = await spinWorld(isGuest);
			await wheel?.spinTo(spun.today!.world);
			revealed = true;
			discover = spun;
		} catch (e) {
			spinError = e instanceof ApiError ? e.detail : 'The wheel could not spin. Try again.';
		} finally {
			spinning = false;
		}
	}

	let today = $derived(discover?.spun ? discover.today : null);
	let look = $derived(today ? worldLook(today.world) : null);
	let title = $derived(discover?.worlds.find((w) => w.key === today?.world)?.title ?? '');
</script>

{#if loadError}
	<div class="py-12 text-center text-white/60">{loadError}</div>
{:else if !discover}
	<div class="py-12 text-center text-white/60">Loading…</div>
{:else if !today || !look}
	<section class="flex flex-col items-center gap-6 py-2 text-center">
		<div class="space-y-2">
			<h2 class="text-2xl font-bold text-white sm:text-3xl">Spin for today's world</h2>
			<p class="mx-auto max-w-md text-white/70">One spin a day lands you in a world of anime to discover.</p>
		</div>
		<DiscoverWheel bind:this={wheel} worlds={discover.worlds} disabled={spinning} onspin={spin} />
		<button
			type="button"
			class="rounded-full bg-primary px-7 py-2.5 text-base font-semibold text-primary-foreground shadow-lg shadow-primary/30 transition hover:brightness-110 disabled:opacity-60"
			disabled={spinning}
			onclick={spin}
		>
			{spinning ? 'Spinning…' : 'Spin the wheel'}
		</button>
		{#if spinError}
			<p class="text-sm text-white/80">{spinError}</p>
		{/if}
	</section>
{:else}
	<!-- The flash a back link lands with takes the world's colour too; its token is mixed
	     where it is declared (`app.css`), so overriding `--primary` alone would not reach it. -->
	<div
		class="world space-y-8"
		class:reveal={revealed}
		style:--primary={look.color}
		style:--ring={look.color}
		style:--focus-sweep-tint="color-mix(in oklab, {look.color} 45%, transparent)"
	>
		<!-- `bg-origin-border`: the gradient spans the border box, so the 1px border shows the
		     banner's own edge rather than the gradient's far end repeated into it. -->
		<header
			class="relative overflow-hidden rounded-2xl border border-white/15 bg-origin-border px-6 py-9 shadow-lg sm:px-10 sm:py-12"
			style:background-image="linear-gradient(115deg, color-mix(in oklab, {look.color} 62%, transparent), color-mix(in oklab, {look.color} 14%, transparent) 70%)"
		>
			<WorldParticles glyph={look.particle.glyph} motion={look.particle.motion} color={look.color} />
			<!-- `opacity` on the whole icon, not a translucent colour, so its overlapping strokes
			     don't add up where they cross. -->
			<look.icon class="absolute -bottom-10 -right-6 size-52 rotate-12 text-white opacity-20 sm:size-64" aria-hidden="true" />
			<div class="relative">
				<h2 class="text-4xl font-black tracking-tight text-white drop-shadow sm:text-5xl">{title}</h2>
				<p class="mt-3 text-white/85">Today's world. Spin the wheel again tomorrow.</p>
			</div>
		</header>
		<div>
			<BrowsePageRows page="discover" carousels={today.carousels} />
		</div>
	</div>
{/if}

<style>
	.reveal > header {
		animation: unfold 650ms cubic-bezier(0.2, 0.9, 0.3, 1.15) both;
	}
	.reveal > div {
		animation: rows-in 500ms ease-out 250ms both;
	}
	@keyframes unfold {
		from { transform: scale(0.9); opacity: 0; }
		to { transform: scale(1); opacity: 1; }
	}
	@keyframes rows-in {
		from { transform: translateY(1rem); opacity: 0; }
		to { transform: translateY(0); opacity: 1; }
	}
	@media (prefers-reduced-motion: reduce) {
		.reveal > header,
		.reveal > div {
			animation: none;
		}
	}
</style>
