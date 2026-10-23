<script lang="ts">
	// A mood's ambient layer: its glyph drifting over whatever holds the layer — or, for a
	// mood whose particles fly, its bat crossing it with its wings beating. Pure CSS, sized in
	// container units so the keyframes fit whatever size of banner holds them.
	import { BAT, particles, type ParticleMotion } from '$lib/utils/discoverMoods';

	interface Props {
		glyph: string;
		motion: ParticleMotion;
		color: string;
	}

	let { glyph, motion, color }: Props = $props();
	const shown = particles(16);
	// A bat crosses the whole banner, so fewer fill it. It takes its time, at the reveal's
	// pace, and its start is stretched by as much so the flock stays spread along the way.
	const flock = particles(7);
	const LAZY = 3;
</script>

<div
	class="layer"
	aria-hidden="true"
	style:--mood={color}
	style:--hinge="{BAT.shoulder.x}px {BAT.shoulder.y}px"
	style:--up="{BAT.beat[0]}deg"
	style:--down="{BAT.beat[1]}deg"
>
	{#if motion === 'fly'}
		{#each flock as p, i (i)}
			<!-- Every other bat flies the other way; a bat is symmetric, so it needs no flip. -->
			<svg
				class="bat"
				class:back={i % 2}
				viewBox="0 0 100 60"
				style:top="{p.top}%"
				style:width="{p.size * 2.4}rem"
				style:animation-duration="{p.duration * LAZY}s"
				style:animation-delay="{p.delay * LAZY}s"
				style:--beat="{0.32 + (i % 4) * 0.05}s"
			>
				<path d={BAT.body} />
				<path class="wing" d={BAT.wing} />
				<!-- Mirrored by its group, so the wing's own CSS transform beats inside the mirror. -->
				<g transform="matrix(-1 0 0 1 100 0)"><path class="wing" d={BAT.wing} /></g>
			</svg>
		{/each}
	{:else}
		{#each shown as p, i (i)}
			<span
				class="particle {motion}"
				style:left="{p.left}%"
				style:top={motion === 'drift' || motion === 'twinkle' ? `${p.top}%` : null}
				style:font-size="{p.size}rem"
				style:animation-duration="{p.duration}s"
				style:animation-delay="{p.delay}s">{glyph}</span
			>
		{/each}
	{/if}
</div>

<style>
	.layer {
		position: absolute;
		inset: 0;
		overflow: hidden;
		pointer-events: none;
		container-type: size;
	}
	.particle {
		position: absolute;
		line-height: 1;
		color: var(--mood);
		text-shadow: 0 0 0.6em var(--mood);
		opacity: 0;
		animation-iteration-count: infinite;
		animation-timing-function: linear;
	}
	.rise {
		bottom: -1.5rem;
		animation-name: rise;
	}
	.fall {
		top: -1.5rem;
		animation-name: fall;
	}
	.drift {
		animation-name: drift;
		animation-timing-function: ease-in-out;
	}
	.twinkle {
		animation-name: twinkle;
		animation-timing-function: ease-in-out;
	}
	.bat {
		position: absolute;
		left: -12%;
		overflow: visible;
		fill: var(--mood);
		/* The glow hugs the silhouette and its beating wings. The wings repaint the bat every
		   frame anyway, so the shadow re-run with them is a small cost on a bat this size. */
		filter: drop-shadow(0 0 0.3rem var(--mood));
		opacity: 0;
		animation: fly linear infinite;
	}
	/* The same flight played backwards: in from the right, out on the left. */
	.bat.back {
		animation-direction: reverse;
	}
	.wing {
		transform-box: view-box;
		transform-origin: var(--hinge);
		animation: beat var(--beat) ease-in-out infinite alternate;
	}
	@keyframes rise {
		0% { transform: translate(0, 0); opacity: 0; }
		15% { opacity: 0.9; }
		100% { transform: translate(3cqw, -115cqh); opacity: 0; }
	}
	@keyframes fall {
		0% { transform: translate(0, 0) rotate(0deg); opacity: 0; }
		10% { opacity: 0.9; }
		50% { transform: translate(4cqw, 58cqh) rotate(140deg); }
		100% { transform: translate(-3cqw, 118cqh) rotate(280deg); opacity: 0.3; }
	}
	@keyframes drift {
		0%, 100% { transform: translate(0, 0); opacity: 0; }
		25%, 75% { opacity: 0.8; }
		50% { transform: translate(7cqw, -12cqh); }
	}
	@keyframes twinkle {
		0%, 100% { transform: scale(0.3); opacity: 0; }
		50% { transform: scale(1); opacity: 0.95; }
	}
	/* Across the banner and out the far side, rising and dipping as it goes. */
	@keyframes fly {
		0% { transform: translate(0, 0); opacity: 0; }
		8%, 92% { opacity: 0.85; }
		30% { transform: translate(38cqw, -7cqh); }
		60% { transform: translate(76cqw, 5cqh); }
		100% { transform: translate(124cqw, -3cqh); opacity: 0; }
	}
	@keyframes beat {
		from { transform: rotate(var(--up)); }
		to { transform: rotate(var(--down)); }
	}
	@media (prefers-reduced-motion: reduce) {
		.layer {
			display: none;
		}
	}
</style>
