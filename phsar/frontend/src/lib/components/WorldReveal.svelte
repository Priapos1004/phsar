<script lang="ts">
	// Discover's reveal: the cut from the wheel to the world, played full screen as a beat from
	// an anime opening. Letterbox bars and a dimmed screen first, so there is a moment of
	// anticipation; then the world's signature (a punching one lands with a hit-stop and an
	// impact frame), the flash and the title card.
	//
	// Above the navbar on purpose: it is over in seconds, so it never contradicts the
	// navbar keeping the user's theme. Two full-screen flashes at most, the impact frame and the
	// peak, which keeps it under WCAG 2.3.1's three a second; a signature flickers only its own
	// small shapes. The canvas side is `utils/worldReveal.ts`.
	import { onDestroy, tick } from 'svelte';
	import { reducedMotion, worldLook, type WorldLook } from '$lib/utils/discoverWorlds';
	import { BEAT, runReveal, softness } from '$lib/utils/worldReveal';

	const SKIP_FADE_MS = 160;
	// Where the glyph burst flies, in vmin from the centre: evenly round, off the axes.
	const BURST = Array.from({ length: 12 }, (_, i) => {
		const a = (i / 12) * Math.PI * 2 + 0.26;
		return { dx: Math.cos(a) * 46, dy: Math.sin(a) * 46, turn: (i % 2 ? 1 : -1) * (40 + i * 9) };
	});

	let shown = $state<{ look: WorldLook; title: string } | null>(null);
	let leaving = $state(false);
	let canvas = $state<HTMLCanvasElement>();
	let timers: ReturnType<typeof setTimeout>[] = [];
	let stopCanvas = () => {};
	let atPeak = () => {};

	/** Play `key`'s reveal. Resolves at the flash peak, when the page underneath may swap — at
	 *  once under reduced motion, which plays nothing. */
	export async function play(key: string, title: string): Promise<void> {
		if (reducedMotion()) return;
		finish();
		shown = { look: worldLook(key), title };
		await tick();
		if (canvas) stopCanvas = runReveal(canvas, shown.look);
		return new Promise((resolve) => {
			atPeak = () => resolve();
			timers = [setTimeout(peak, BEAT.peak), setTimeout(finish, BEAT.end)];
		});
	}

	function peak() {
		atPeak();
		atPeak = () => {};
	}

	function clearTimers() {
		timers.forEach(clearTimeout);
		timers = [];
	}

	// Always lets the spin waiting on `play` go on, so a reveal ending early — skipped, or
	// unmounted with the tab — can never leave the wheel stuck on "Spinning…".
	function finish() {
		clearTimers();
		stopCanvas();
		stopCanvas = () => {};
		peak();
		shown = null;
		leaving = false;
	}

	function skip() {
		if (!shown || leaving) return;
		peak();
		leaving = true;
		clearTimers();
		timers = [setTimeout(finish, SKIP_FADE_MS)];
	}

	onDestroy(finish);
</script>

<svelte:window onpointerdown={skip} onkeydown={skip} />

{#if shown}
	{@const { look, title } = shown}
	{@const soft = softness(look.reveal)}
	<div
		class="stage"
		class:leaving
		data-kind={look.reveal}
		aria-hidden="true"
		style:--world={look.color}
		style:--wash="{soft?.wash ?? 0}%"
		style:--t-impact="{BEAT.impact}ms"
		style:--t-peak="{BEAT.peak}ms"
		style:--t-title="{BEAT.title}ms"
		style:--t-clear="{BEAT.clear}ms"
		style:--skip-fade="{SKIP_FADE_MS}ms"
	>
		<!-- The shake moves everything inside the frame and never the frame itself, the way a camera
		     shakes under its letterbox. Its overhang keeps the page from showing at the edges. -->
		<div class="shake" class:punch={!soft}>
			<div class="dim"></div>
			<canvas bind:this={canvas}></canvas>
			<div class="flash"></div>
			{#if !soft || soft.ring}
				<div class="ring"></div>
			{/if}
			{#if !soft}
				{#each BURST as b}
					<span class="glyph" style:--dx="{b.dx}vmin" style:--dy="{b.dy}vmin" style:--turn="{b.turn}deg">{look.particle.glyph}</span>
				{/each}
			{/if}
			<div class="card">
				<p class="kicker">Today's mood</p>
				<p class="name"><span class="swipe"></span><span class="relative">{title}</span></p>
			</div>
		</div>
		<!-- Cinema black, whatever the theme: the bars are the camera's frame, not the page. -->
		<div class="bar top"></div>
		<div class="bar bottom"></div>
	</div>
{/if}

<style>
	.stage {
		position: fixed;
		inset: 0;
		z-index: 60;
		overflow: hidden;
		/* Takes the tap that skips it: let through, its click would land on the rows already
		   swapped in underneath. */
		transition: opacity var(--skip-fade) ease-out;
	}
	.stage.leaving {
		opacity: 0;
	}
	.shake,
	.shake > * {
		position: absolute;
	}
	.shake {
		inset: -24px;
	}
	.shake.punch {
		animation: shake 440ms linear var(--t-impact) both;
	}
	.dim,
	canvas,
	.flash {
		inset: 0;
		width: 100%;
		height: 100%;
	}
	.dim {
		background: radial-gradient(circle, color-mix(in oklab, var(--world) 24%, black), black 75%);
		animation:
			dim-in 360ms ease-out both,
			dim-out 450ms ease-in var(--t-clear) forwards;
	}
	/* A hard cut to white, then a long fall-off — not a fade in. A soft signature washes in
	   its colour instead, as strongly as its `wash`. */
	.flash {
		background: color-mix(in oklab, var(--world) var(--wash), transparent);
		opacity: 0;
		animation: flash 480ms cubic-bezier(0.3, 0, 0.6, 1) var(--t-peak) forwards;
	}
	.punch .flash {
		background: color-mix(in oklab, var(--world) 14%, white);
	}
	.ring {
		inset: 0;
		margin: auto;
		width: 40vmin;
		height: 40vmin;
		border-radius: 50%;
		border: 3px solid var(--world);
		box-shadow:
			0 0 28px var(--world),
			inset 0 0 28px var(--world);
		opacity: 0;
		animation: ring 720ms cubic-bezier(0.1, 0.7, 0.3, 1) var(--t-peak) forwards;
	}
	.glyph {
		left: 50%;
		top: 50%;
		font-size: 2rem;
		line-height: 1;
		color: var(--world);
		text-shadow: 0 0 0.5em var(--world);
		opacity: 0;
		animation: burst 820ms cubic-bezier(0.15, 0.8, 0.3, 1) var(--t-peak) forwards;
	}
	.card {
		inset: 0;
		display: flex;
		flex-direction: column;
		align-items: center;
		justify-content: center;
		gap: 0.5rem;
		padding: 0 6vw;
		text-align: center;
		/* The hold is a slow push-in, so the card isn't a still frame while it is read. */
		--card-in: 460ms;
		animation:
			card-in var(--card-in) cubic-bezier(0.2, 1.35, 0.4, 1) var(--t-title) both,
			card-hold calc(var(--t-clear) - var(--t-title) - var(--card-in)) linear calc(var(--t-title) + var(--card-in)) forwards,
			card-out 380ms ease-in var(--t-clear) forwards;
	}
	.kicker {
		font-size: 0.8rem;
		font-weight: 700;
		letter-spacing: 0.5em;
		text-transform: uppercase;
		color: rgb(255 255 255 / 0.85);
	}
	.name {
		position: relative;
		max-width: 16ch;
		font-size: clamp(2.4rem, 9vw, 6.5rem);
		font-style: italic;
		font-weight: 900;
		line-height: 0.95;
		letter-spacing: -0.03em;
		text-transform: uppercase;
		text-wrap: balance;
		color: white;
		text-shadow:
			0 0 0.35em var(--world),
			0 0.06em 0 rgb(0 0 0 / 0.5);
	}
	/* A glitch signature's title arrives as a broken signal and stutters once mid-hold. The cyan and
	   magenta are a split signal's, whatever the theme. */
	[data-kind='glitch'] .name {
		animation:
			name-glitch 420ms steps(1, end) var(--t-title) both,
			name-glitch 260ms steps(1, end) calc(var(--t-title) + 900ms);
	}
	.swipe {
		position: absolute;
		left: -0.4em;
		right: -0.4em;
		top: 38%;
		height: 0.42em;
		background: var(--world);
		transform-origin: left;
		animation: swipe 300ms cubic-bezier(0.6, 0, 0.2, 1) var(--t-title) both;
	}
	.bar {
		left: 0;
		right: 0;
		position: absolute;
		height: 11vh;
		background: #000;
		animation:
			bar-in 340ms cubic-bezier(0.2, 0.8, 0.2, 1) both,
			bar-out 380ms ease-in var(--t-clear) forwards;
	}
	.bar.top {
		top: 0;
		transform-origin: top;
	}
	.bar.bottom {
		bottom: 0;
		transform-origin: bottom;
	}

	@keyframes dim-in {
		from { opacity: 0; }
		to { opacity: 0.86; }
	}
	/* The exits name only their end and fill forwards: filling backwards, a later animation in
	   the list would hold its start over the entrance before it. */
	@keyframes dim-out {
		to { opacity: 0; }
	}
	@keyframes flash {
		from { opacity: 1; }
		to { opacity: 0; }
	}
	@keyframes ring {
		from { transform: scale(0.1); opacity: 1; }
		to { transform: scale(3.4); opacity: 0; }
	}
	@keyframes burst {
		from { transform: translate(-50%, -50%) scale(0.4); opacity: 1; }
		to { transform: translate(calc(-50% + var(--dx)), calc(-50% + var(--dy))) scale(1.15) rotate(var(--turn)); opacity: 0; }
	}
	@keyframes card-in {
		0% { transform: scale(1.9); opacity: 0; }
		35% { opacity: 1; }
		100% { transform: scale(1); opacity: 1; }
	}
	@keyframes card-hold {
		to { transform: scale(1.06); }
	}
	@keyframes card-out {
		to { transform: scale(1.12); opacity: 0; }
	}
	@keyframes name-glitch {
		0% { clip-path: inset(10% 0 60% 0); transform: translateX(-8px); text-shadow: -3px 0 #0ff, 3px 0 #f0f; }
		15% { clip-path: inset(50% 0 20% 0); transform: translateX(10px); }
		30% { clip-path: inset(0 0 80% 0); transform: translateX(-4px); }
		45% { clip-path: inset(70% 0 5% 0); transform: translateX(6px); }
		60% { clip-path: inset(20% 0 40% 0); transform: translateX(-10px); }
		75% { clip-path: inset(0); transform: translateX(3px); text-shadow: -2px 0 #0ff, 2px 0 #f0f; }
		/* Held through the card: the inset crops the swipe and the glow to the title's box. */
		100% { clip-path: inset(0); }
	}
	@keyframes swipe {
		from { transform: skewX(-14deg) scaleX(0); }
		to { transform: skewX(-14deg) scaleX(1); }
	}
	@keyframes bar-in {
		from { transform: scaleY(0); }
		to { transform: scaleY(1); }
	}
	@keyframes bar-out {
		to { transform: scaleY(0); }
	}
	/* Decaying: the hardest jolt first. */
	@keyframes shake {
		0% { transform: translate(0, 0); }
		8% { transform: translate(-16px, 9px); }
		18% { transform: translate(13px, -11px); }
		32% { transform: translate(-9px, 6px); }
		48% { transform: translate(6px, -4px); }
		66% { transform: translate(-3px, 2px); }
		100% { transform: translate(0, 0); }
	}
</style>
