<script lang="ts">
	import * as Card from '$lib/components/ui/card';
	import { formatNumber, percentOf } from '$lib/utils/formatString';
	import type { AdminSweepTierBreakdown } from '$lib/types/api';

	interface Props {
		animeTiers: AdminSweepTierBreakdown;
		mediaTiers: AdminSweepTierBreakdown;
	}
	let { animeTiers, mediaTiers }: Props = $props();

	// v0.14.8: refresh selection went media-level, but the cadence-membership
	// view is useful at both grains — anime ("where does each umbrella sit")
	// and media ("which rows actually drive nightly refresh"). Toggle, default
	// anime to preserve the prior view. Membership, not due-ness: each count is
	// where a row *sits* in the cycle, a stable trait, so rows don't empty
	// themselves the moment a nightly sweep refreshes their members.
	let mode = $state<'anime' | 'media'>('anime');
	let tiers = $derived(mode === 'anime' ? animeTiers : mediaTiers);

	// Display buckets map 1:1 to the backend's 4 mutually-exclusive
	// cycle-membership tiers (priority cascade). Tooltips paraphrase each
	// predicate; the stabilize (< 5 sweeps) and long-cycle (90-day) borders
	// are shared by both grains (v0.14.8 unified both thresholds).
	const ROWS: {
		key: keyof AdminSweepTierBreakdown;
		label: string;
		color: string;
		tooltip: (mode: 'anime' | 'media') => string;
	}[] = [
		{
			key: 'airing_now',
			label: 'Airing now',
			color: 'bg-emerald-500',
			tooltip: (m) =>
				m === 'anime'
					? 'Has at least one currently-airing media. Refreshed every nightly sweep.'
					: 'This media is currently airing. Refreshed every nightly sweep.',
		},
		{
			key: 'stabilizing',
			label: 'Stabilizing',
			color: 'bg-amber-500',
			tooltip: () => 'In the first 5 sweeps of its lifecycle (stable_check_count < 5).',
		},
		{
			key: 'weekly_cycle',
			label: 'Weekly cycle',
			color: 'bg-sky-500',
			tooltip: (m) =>
				m === 'anime'
					? 'Has a main media aired within the recent-main window — on the weekly refresh cadence.'
					: 'A main media aired within the recent-main window — on the weekly refresh cadence.',
		},
		{
			key: 'long_cycle',
			label: '90-day cycle',
			color: 'bg-indigo-500',
			tooltip: (m) =>
				m === 'anime'
					? 'Stable + not airing + no recent main — its media resurface only on the 90-day safety net.'
					: 'Stable + not airing + not a recent main — refreshed only on the 90-day safety net.',
		},
	];

	let total = $derived(ROWS.reduce((acc, row) => acc + (tiers[row.key] ?? 0), 0));
</script>

<Card.Root>
	<Card.Header>
		<div class="flex items-center justify-between gap-3 flex-wrap">
			<h2 class="text-lg font-semibold text-card-foreground">Sweep tiers</h2>
			<div class="flex gap-1">
				{#each [{ key: 'anime', label: 'Anime' }, { key: 'media', label: 'Media' }] as opt (opt.key)}
					<button
						type="button"
						class="px-2 py-1 rounded-full text-xs border transition-colors {mode === opt.key
							? 'border-primary bg-primary/15 text-primary'
							: 'border-border text-muted-foreground hover:bg-muted/30'}"
						onclick={() => (mode = opt.key as 'anime' | 'media')}
					>
						{opt.label}
					</button>
				{/each}
			</div>
		</div>
		<p class="text-xs text-muted-foreground">
			Where every {mode} currently sits in the update-sweep cycle.
			Buckets are mutually exclusive — sum equals {mode} total ({formatNumber(total)}).
		</p>
	</Card.Header>
	<Card.Content>
		<div class="space-y-2">
			{#each ROWS as row (row.key)}
				{@const count = tiers[row.key] ?? 0}
				{@const share = percentOf(count, total)}
				<div class="flex items-center gap-3 text-sm" title={row.tooltip(mode)}>
					<div class="w-40 shrink-0 text-card-foreground/90">{row.label}</div>
					<div class="flex-1 h-2 rounded-full bg-muted/40 overflow-hidden">
						<div class="h-full {row.color}" style="width: {share}%"></div>
					</div>
					<div class="w-14 shrink-0 text-right tabular-nums text-card-foreground font-medium">
						{formatNumber(count)}
					</div>
					<div class="w-12 shrink-0 text-right tabular-nums text-xs text-muted-foreground">
						{share.toFixed(1)}%
					</div>
				</div>
			{/each}
		</div>
	</Card.Content>
</Card.Root>
