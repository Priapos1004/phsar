<script lang="ts">
	import { ArrowUp, ArrowDown } from 'lucide-svelte';
	import { formatShortDate } from '$lib/utils/formatString';
	import { rowClickNavigate } from '$lib/utils/navigation';
	import { priorityLabel, PRIORITY_ACCENT, tagGradient } from '$lib/utils/watchlist';
	import Tooltip from '$lib/components/Tooltip.svelte';
	import * as cls from '$lib/styles/classes';
	import type { WatchlistRow, WatchlistSortKey } from '$lib/utils/watchlistStats';

	interface Props {
		rows: WatchlistRow[];
		sort: WatchlistSortKey;
		sortDir: 'asc' | 'desc';
		onSort: (key: WatchlistSortKey) => void;
	}

	let { rows, sort, sortDir, onSort }: Props = $props();

	const COLS: { key: WatchlistSortKey; label: string; align: 'left' | 'right' | 'center' }[] = [
		{ key: 'title', label: 'Title', align: 'left' },
		{ key: 'priority', label: 'Priority', align: 'center' },
		{ key: 'date', label: 'Added', align: 'right' },
	];
	const alignClass = { left: 'text-left', right: 'text-right', center: 'text-center' } as const;

</script>

<div class="overflow-x-auto rounded-xl border border-border {cls.cardGlass}">
	<table class="w-full text-sm">
		<thead>
			<tr class="text-muted-foreground border-b border-border bg-muted/30">
				<th class="font-medium px-3 py-2.5 text-left w-8"></th>
				{#each COLS as col (col.key)}
					<th class="font-medium px-3 py-2.5 {alignClass[col.align]} {col.key === 'date' ? 'hidden sm:table-cell' : ''}">
						<button class="inline-flex items-center gap-1 hover:text-card-foreground transition-colors" onclick={() => onSort(col.key)}>
							{col.label}
							{#if sort === col.key}
								{#if sortDir === 'asc'}<ArrowUp class="size-3" />{:else}<ArrowDown class="size-3" />{/if}
							{/if}
						</button>
					</th>
				{/each}
			</tr>
		</thead>
		<tbody>
			{#each rows as row (row.key)}
				<!-- svelte-ignore a11y_click_events_have_key_events a11y_no_static_element_interactions -->
				<tr class="border-b border-border/60 last:border-0 hover:bg-muted/40 transition-colors cursor-pointer" onclick={(e) => rowClickNavigate(e, row.href)}>
					<td class="px-3 py-2">
						<Tooltip text={row.tagLabel}>
							<span class="block size-3.5 rounded-full" style="background:{tagGradient(row.colors)}"></span>
						</Tooltip>
					</td>
					<td class="px-3 py-2">
						<a href={row.href} class="text-card-foreground hover:text-primary font-medium">{row.title}</a>
						<span class="ml-1.5 text-xs text-muted-foreground">{row.subtitle}</span>
					</td>
					<td class="px-3 py-2 text-center whitespace-nowrap font-medium {PRIORITY_ACCENT[row.priority].text}">
						{priorityLabel(row.priority)}
					</td>
					<td class="px-3 py-2 text-right text-muted-foreground hidden sm:table-cell whitespace-nowrap">
						{formatShortDate(row.createdAt)}
					</td>
				</tr>
			{/each}
		</tbody>
	</table>
</div>
