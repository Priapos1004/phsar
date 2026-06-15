<script lang="ts">
	import * as Card from '$lib/components/ui/card';
	import { formatNumber, percentOf } from '$lib/utils/formatString';
	import type { AdminSweepTierBreakdown } from '$lib/types/api';

	interface Props {
		tiers: AdminSweepTierBreakdown;
	}
	let { tiers }: Props = $props();

	// Display buckets map 1:1 to the backend's 4 mutually-exclusive
	// cycle-membership tiers (priority cascade). Membership, not due-ness:
	// each count is where an anime *sits* in the cycle, a stable trait, so
	// rows don't empty themselves the moment a nightly sweep refreshes
	// their members. Tooltips paraphrase each predicate.
	const ROWS: {
		key: keyof AdminSweepTierBreakdown;
		label: string;
		color: string;
		tooltip: string;
	}[] = [
		{
			key: 'airing_now',
			label: 'Airing now',
			color: 'bg-emerald-500',
			tooltip: 'Has at least one currently-airing media. Refreshed every nightly sweep.',
		},
		{
			key: 'stabilizing',
			label: 'Stabilizing',
			color: 'bg-amber-500',
			tooltip: 'In the first 3 sweeps of its lifecycle (stable_check_count < 3).',
		},
		{
			key: 'weekly_cycle',
			label: 'Weekly cycle',
			color: 'bg-sky-500',
			tooltip: 'Has a main media aired within the recent-main window — on the weekly refresh cadence.',
		},
		{
			key: 'long_cycle',
			label: '180-day cycle',
			color: 'bg-indigo-500',
			tooltip: 'Stable + not airing + no recent main — refreshed only on the 180-day safety net.',
		},
	];

	let total = $derived(
		ROWS.reduce((acc, row) => acc + (tiers[row.key] ?? 0), 0),
	);
</script>

<Card.Root>
	<Card.Header>
		<h2 class="text-lg font-semibold text-card-foreground">Sweep tiers</h2>
		<p class="text-xs text-muted-foreground">
			Where every anime currently sits in the update-sweep cycle.
			Buckets are mutually exclusive — sum equals catalog total ({formatNumber(total)}).
		</p>
	</Card.Header>
	<Card.Content>
		<div class="space-y-2">
			{#each ROWS as row (row.key)}
				{@const count = tiers[row.key] ?? 0}
				{@const share = percentOf(count, total)}
				<div class="flex items-center gap-3 text-sm" title={row.tooltip}>
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
