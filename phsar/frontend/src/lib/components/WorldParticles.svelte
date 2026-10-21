<script lang="ts">
	// A world's ambient layer: its glyph drifting over whatever holds the layer. Pure CSS,
	// sized in container units so the keyframes fit whatever size of banner holds them.
	import { particles, type ParticleMotion } from '$lib/utils/discoverWorlds';

	interface Props {
		glyph: string;
		motion: ParticleMotion;
		color: string;
	}

	let { glyph, motion, color }: Props = $props();
	const shown = particles(16);
</script>

<div class="layer" aria-hidden="true" style:--world={color}>
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
		color: var(--world);
		text-shadow: 0 0 0.6em var(--world);
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
	@media (prefers-reduced-motion: reduce) {
		.layer {
			display: none;
		}
	}
</style>
