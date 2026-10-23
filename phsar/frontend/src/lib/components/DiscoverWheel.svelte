<script lang="ts">
	// Discover's wheel: a segment per mood, turned onto the mood the backend already drew.
	// The spin is one CSS transition onto `landingRotation`, overshooting a touch before it
	// settles, then a short wobble and the winner lit.
	//
	// Glass and neon like the rest of the app: a translucent disc tinted by each mood,
	// lit by a rim of glowing arcs in the moods' colours. The rotor turns as one HTML box
	// around its own SVG, so the browser composites a drawn layer instead of repainting the
	// gradients and the glow every frame, as a transform on an SVG group makes it.
	import type { DiscoverMood } from '$lib/types/api';
	import { labelLines, landingRotation, reducedMotion, moodLook } from '$lib/utils/discoverMoods';

	interface Props {
		moods: DiscoverMood[];
		disabled?: boolean;
		onspin: () => void;
	}

	let { moods, disabled = false, onspin }: Props = $props();

	const id = $props.id();
	const SPIN_MS = 5200;
	const SETTLE_MS = 900;
	const R = 100;

	let rotation = $state(0);
	let spinning = $state(false);
	let landed = $state<string | null>(null);

	const wait = (ms: number) => new Promise((resolve) => setTimeout(resolve, ms));

	/** Turn onto `key`; resolves once the wheel has settled on it. */
	export async function spinTo(key: string): Promise<void> {
		const index = moods.findIndex((mood) => mood.key === key);
		landed = null;
		if (reducedMotion()) {
			rotation = landingRotation(rotation, index, moods.length, 0);
			landed = key;
			return;
		}
		spinning = true;
		rotation = landingRotation(rotation, index, moods.length, 6, Math.random() - 0.5);
		await wait(SPIN_MS);
		spinning = false;
		landed = key;
		await wait(SETTLE_MS);
	}

	function point(degrees: number, r: number): string {
		const a = ((degrees - 90) * Math.PI) / 180;
		return `${(r * Math.cos(a)).toFixed(2)} ${(r * Math.sin(a)).toFixed(2)}`;
	}

	let segments = $derived(
		moods.map((mood, i) => {
			const size = 360 / moods.length;
			const from = i * size;
			const to = (i + 1) * size;
			return {
				mood,
				look: moodLook(mood.key),
				mid: from + size / 2,
				wedge: `M 0 0 L ${point(from, R)} A ${R} ${R} 0 0 1 ${point(to, R)} Z`,
				arc: `M ${point(from + 2.5, 96)} A 96 96 0 0 1 ${point(to - 2.5, 96)}`,
				lines: labelLines(mood.title),
			};
		}),
	);
	const dim = (key: string) => landed !== null && landed !== key;
</script>

<button
	type="button"
	class="group relative aspect-square w-full max-w-[26rem] rounded-full bg-black/25 shadow-[0_0_90px_-25px_var(--primary)] ring-1 ring-white/15 backdrop-blur-sm outline-offset-4 disabled:cursor-default"
	aria-label="Spin the wheel"
	disabled={disabled || spinning || landed !== null}
	onclick={onspin}
>
	<!-- Both viewBoxes are centred on the hub, so turning the box turns the wheel about it. -->
	<div class="absolute inset-0" class:settle={landed !== null}>
		<div
			class="rotor absolute inset-0"
			style:transform="rotate({rotation}deg)"
			style:transition-duration={spinning ? `${SPIN_MS}ms` : '0ms'}
		>
			<svg viewBox="-112 -112 224 224" class="h-full w-full overflow-visible" aria-hidden="true">
				<defs>
					<filter id="{id}-glow" x="-30%" y="-30%" width="160%" height="160%">
						<feGaussianBlur stdDeviation="2.4" result="blur" />
						<feMerge>
							<feMergeNode in="blur" />
							<feMergeNode in="SourceGraphic" />
						</feMerge>
					</filter>
					{#each segments as s (s.mood.key)}
						<radialGradient id="{id}-{s.mood.key}" cx="0" cy="0" r={R} gradientUnits="userSpaceOnUse">
							<stop offset="0.15" stop-color={s.look.color} stop-opacity="0.04" />
							<stop offset="1" stop-color={s.look.color} stop-opacity="0.42" />
						</radialGradient>
					{/each}
				</defs>
				{#each segments as s (s.mood.key)}
					<path
						class="piece"
						class:dimmed={dim(s.mood.key)}
						class:winner={landed === s.mood.key}
						d={s.wedge}
						fill="url(#{id}-{s.mood.key})"
						stroke="rgb(255 255 255 / 0.14)"
						stroke-width="0.6"
					/>
				{/each}
				<g filter="url(#{id}-glow)">
					{#each segments as s (s.mood.key)}
						<path class="piece" class:dimmed={dim(s.mood.key)} d={s.arc} fill="none" stroke={s.look.color} stroke-width="3" stroke-linecap="round" />
						<g class="piece" class:dimmed={dim(s.mood.key)} transform="rotate({s.mid}) translate(0 -80)">
							<s.look.icon x={-8.5} y={-8.5} size={17} color={s.look.color} strokeWidth={2.2} />
						</g>
					{/each}
				</g>
				<!-- Centred by `dy`, not `dominant-baseline`: not every engine passes that down to a
				     `<tspan>`, and one that doesn't sets the lines on their alphabetic baseline, a
				     third of an em off the segment's centre line. The 0.35em drops the baseline far
				     enough to put the middle of a capital on the anchor. -->
				{#each segments as s (s.mood.key)}
					<text
						class="piece"
						class:dimmed={dim(s.mood.key)}
						transform="rotate({s.mid}) translate(0 -47) rotate(-90)"
						text-anchor="middle"
						font-size="6.4"
						font-weight="700"
						fill="white"
						fill-opacity="0.92"
					>
						{#each s.lines as line, i (i)}
							<tspan x="0" dy={i === 0 ? `${0.35 - (s.lines.length - 1) * 0.55}em` : '1.1em'}>{line}</tspan>
						{/each}
					</text>
				{/each}
			</svg>
		</div>
	</div>
	<svg viewBox="-112 -112 224 224" class="absolute inset-0 h-full w-full overflow-visible" aria-hidden="true">
		<circle r={R} fill="none" stroke="rgb(255 255 255 / 0.22)" stroke-width="1" />
		<circle r="16" fill="rgb(255 255 255 / 0.1)" stroke="rgb(255 255 255 / 0.3)" stroke-width="0.8" />
		<g filter="url(#{id}-glow)">
			<circle r="6.5" class="fill-primary transition group-enabled:group-hover:opacity-75" />
			<path d="M -8 -115 L 8 -115 L 0 -98 Z" fill="white" />
		</g>
	</svg>
</button>

<style>
	.rotor {
		will-change: transform;
		transition-property: transform;
		/* y2 just above 1: a few degrees past the stop, then back onto it. */
		transition-timing-function: cubic-bezier(0.12, 0.78, 0.18, 1.004);
	}
	.piece {
		transition: opacity 400ms ease;
	}
	.piece.dimmed {
		opacity: 0.25;
	}
	.piece.winner {
		stroke: rgb(255 255 255 / 0.75);
		stroke-width: 1.4;
		transition: stroke 400ms ease, stroke-width 400ms ease;
	}
	.settle {
		animation: settle 700ms ease-out;
	}
	@keyframes settle {
		0% { transform: rotate(0deg); }
		30% { transform: rotate(2.5deg); }
		60% { transform: rotate(-1.4deg); }
		85% { transform: rotate(0.5deg); }
		100% { transform: rotate(0deg); }
	}
	@media (prefers-reduced-motion: reduce) {
		.settle {
			animation: none;
		}
	}
</style>
