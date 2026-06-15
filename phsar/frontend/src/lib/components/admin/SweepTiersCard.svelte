<script lang="ts">
	import * as Card from '$lib/components/ui/card';
	import { formatNumber, percentOf } from '$lib/utils/formatString';
	import type { AdminSweepTierBreakdown } from '$lib/types/api';

	interface Props {
		tiers: AdminSweepTierBreakdown;
	}
	let { tiers }: Props = $props();

	// Display buckets. The backend exposes 5 mutually-exclusive tiers but
	// we fold long_tail + not_currently_due into a single row: long_tail
	// is a transient state that empties as soon as the next sweep
	// refreshes those anime back into not_currently_due, so showing them
	// separately misleads the admin into thinking they're chronically
	// distinct. Tooltips paraphrase each predicate.
	const ROWS: {
		key: string;
		sources: (keyof AdminSweepTierBreakdown)[];
		label: string;
		color: string;
		tooltip: string;
	}[] = [
		{
			key: 'airing_now',
			sources: ['airing_now'],
			label: 'Airing now',
			color: 'bg-emerald-500',
			tooltip: 'Has at least one currently-airing media. Refreshed every nightly sweep.',
		},
		{
			key: 'stabilizing',
			sources: ['stabilizing'],
			label: 'Stabilizing',
			color: 'bg-amber-500',
			tooltip: 'In the first 3 sweeps of its lifecycle (stable_check_count < 3).',
		},
		{
			key: 'weekly_recent_main',
			sources: ['weekly_recent_main'],
			label: 'Weekly recent main',
			color: 'bg-sky-500',
			tooltip: 'Last checked > 7 days ago AND has main media aired within the recent-main window. Weekly cycle.',
		},
		{
			key: 'long_cycle',
			sources: ['long_tail', 'not_currently_due'],
			label: '180-day cycle',
			color: 'bg-indigo-500',
			tooltip: 'Stable + not airing + no recent main. Refreshed on the long-tail safety net (≥180 days since last check).',
		},
	];

	function countFor(sources: (keyof AdminSweepTierBreakdown)[]): number {
		return sources.reduce((acc, key) => acc + (tiers[key] ?? 0), 0);
	}

	let total = $derived(
		ROWS.reduce((acc, row) => acc + countFor(row.sources), 0),
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
				{@const count = countFor(row.sources)}
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
