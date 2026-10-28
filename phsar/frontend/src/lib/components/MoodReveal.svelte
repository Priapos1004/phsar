<script lang="ts">
	// Discover's reveal: the cut from the wheel to the mood, played full screen as a beat from
	// an anime opening. Letterbox bars and a dimmed screen first, so there is a moment of
	// anticipation; then the mood's signature (a punching one lands with a hit-stop and an
	// impact frame), the flash and the title card.
	//
	// Above the navbar on purpose: it is over in seconds, so it never contradicts the
	// navbar keeping the user's theme. Two full-screen flashes at most, the impact frame and the
	// peak, which keeps it under WCAG 2.3.1's three a second; a signature flickers only its own
	// small shapes. The canvas side is `utils/moodReveal.ts`.
	import { onDestroy, tick } from 'svelte';
	import { reducedMotion, moodLook, type MoodLook } from '$lib/utils/discoverMoods';
	import { BEAT, runReveal, softness } from '$lib/utils/moodReveal';

	const SKIP_FADE_MS = 160;
	// Where the glyph burst flies, in vmin from the centre: evenly round, off the axes.
	const BURST = Array.from({ length: 12 }, (_, i) => {
		const a = (i / 12) * Math.PI * 2 + 0.26;
		return { dx: Math.cos(a) * 46, dy: Math.sin(a) * 46, turn: (i % 2 ? 1 : -1) * (40 + i * 9) };
	});

	let shown = $state<{ look: MoodLook; title: string } | null>(null);
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
		shown = { look: moodLook(key), title };
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
		style:--mood={look.color}
		style:--wash="{soft?.wash ?? 0}%"
		style:--t-impact="{BEAT.impact}ms"
		style:--t-peak="{BEAT.peak}ms"
		style:--t-title="{BEAT.title}ms"
		style:--t-print="{BEAT.print}ms"
		style:--t-printed="{BEAT.printed}ms"
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
				<p class="name" data-title={title}><span class="swipe"></span><span class="letters relative">{title}</span></p>
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
		background: radial-gradient(circle, color-mix(in oklab, var(--mood) 24%, black), black 75%);
		animation:
			dim-in 360ms ease-out both,
			dim-out 450ms ease-in var(--t-clear) forwards;
	}
	/* A hard cut to white, then a long fall-off — not a fade in. A soft signature washes in
	   its colour instead, as strongly as its `wash`. */
	.flash {
		background: color-mix(in oklab, var(--mood) var(--wash), transparent);
		opacity: 0;
		animation: flash 480ms cubic-bezier(0.3, 0, 0.6, 1) var(--t-peak) forwards;
	}
	.punch .flash {
		background: color-mix(in oklab, var(--mood) 14%, white);
	}
	.ring {
		inset: 0;
		margin: auto;
		width: 40vmin;
		height: 40vmin;
		border-radius: 50%;
		border: 3px solid var(--mood);
		box-shadow:
			0 0 28px var(--mood),
			inset 0 0 28px var(--mood);
		opacity: 0;
		animation: ring 720ms cubic-bezier(0.1, 0.7, 0.3, 1) var(--t-peak) forwards;
	}
	.glyph {
		left: 50%;
		top: 50%;
		font-size: 2rem;
		line-height: 1;
		color: var(--mood);
		text-shadow: 0 0 0.5em var(--mood);
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
			0 0 0.35em var(--mood),
			0 0.06em 0 rgb(0 0 0 / 0.5);
	}
	/* The ufo prints its title rather than punching it in: the card fades up on a hologram's
	   wireframe — a copy of the title (`data-title`) outlined in the mood's colour and ruled with
	   scanlines — and a scan line sweeps down it, leaving the letters solid above it. The swipe
	   waits until there are letters to underline. */
	[data-kind='ufo'] {
		--print-ms: calc(var(--t-printed) - var(--t-print));
		--print-ease: cubic-bezier(0.45, 0, 0.55, 1);
	}
	[data-kind='ufo'] .card {
		animation-name: card-fade, card-hold, card-out;
	}
	[data-kind='ufo'] .letters {
		display: block;
		animation: name-print var(--print-ms) var(--print-ease) var(--t-print) both;
	}
	[data-kind='ufo'] .name::before {
		content: attr(data-title);
		position: absolute;
		inset: 0;
		color: transparent;
		text-shadow: none;
		-webkit-text-stroke: max(1px, 0.015em) var(--mood);
		background: repeating-linear-gradient(rgb(255 255 255 / 0.4) 0 1px, transparent 1px max(3px, 0.05em));
		background-clip: text;
		filter: drop-shadow(0 0 0.08em var(--mood));
		/* In by the time the print starts, out once it is printed. */
		animation:
			card-fade calc(var(--t-print) - var(--t-title)) linear var(--t-title) both,
			dim-out 250ms linear var(--t-printed) forwards;
	}
	/* The scan line is this box's top border. The box spans the title, so it travels as a
	   transform — the compositor's work — by a share of its own height. */
	[data-kind='ufo'] .name::after {
		content: '';
		position: absolute;
		inset: 0 -0.3em;
		border-top: max(2px, 0.03em) solid #fff;
		filter: drop-shadow(0 0 0.15em var(--mood)) drop-shadow(0 0 0.3em var(--mood));
		animation: name-scan var(--print-ms) var(--print-ease) var(--t-print) both;
	}
	[data-kind='ufo'] .swipe {
		animation-delay: var(--t-printed);
	}
	.swipe {
		position: absolute;
		left: -0.4em;
		right: -0.4em;
		top: 38%;
		height: 0.42em;
		background: var(--mood);
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
	@keyframes card-fade {
		from { opacity: 0; }
	}
	/* The clip's lower edge and the scan line travel together. Printed, the clip reaches 1em past
	   the box, so the glow isn't cropped. */
	@keyframes name-print {
		from { clip-path: inset(0 -1em 100% -1em); }
		to { clip-path: inset(-1em); }
	}
	@keyframes name-scan {
		85% { opacity: 1; }
		to { transform: translateY(calc(100% + 1em)); opacity: 0; }
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
