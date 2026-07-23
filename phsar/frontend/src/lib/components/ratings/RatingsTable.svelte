<script lang="ts">
	import { ArrowUp, ArrowDown } from 'lucide-svelte';
	import { Badge } from '$lib/components/ui/badge';
	import { scoreColor } from '$lib/utils/chartColors';
	import { formatDecimalDigits, formatShortDate, resolveTitle } from '$lib/utils/formatString';
	import { buildDetailHref, rowClickNavigate } from '$lib/utils/navigation';
	import * as cls from '$lib/styles/classes';
	import { mainSideLabel } from '$lib/utils/relations';
	import { type AnimeRatingRow, type SortKey } from '$lib/utils/ratingStats';

	interface Props {
		rows: AnimeRatingRow[];
		nameLanguage: 'english' | 'japanese' | 'romaji';
		scoreDecimals: number;
		sort: SortKey;
		sortDir: 'asc' | 'desc';
		onSort: (key: SortKey) => void;
	}

	let { rows, nameLanguage, scoreDecimals, sort, sortDir, onSort }: Props = $props();

	// Every column is sortable; the table replaces the standalone sort + status controls.
	const COLS: { key: SortKey; label: string; align: 'left' | 'right' | 'center'; hide?: string }[] = [
		{ key: 'title', label: 'Title', align: 'left' },
		{ key: 'score', label: 'Your', align: 'right' },
		{ key: 'mal', label: 'MAL', align: 'right', hide: 'hidden sm:table-cell' },
		{ key: 'malDelta', label: 'Δ', align: 'right' },
		{ key: 'status', label: 'Status', align: 'center' },
		{ key: 'date', label: 'Rated', align: 'right', hide: 'hidden sm:table-cell' },
	];
	const alignClass = { left: 'text-left', right: 'text-right', center: 'text-center' } as const;
</script>

<!-- Table lives on a light card surface, so all text is card/muted-foreground (never white). -->
<div class="overflow-x-auto rounded-xl border border-border {cls.cardGlass}">
	<table class="w-full text-sm">
		<thead>
			<tr class="text-muted-foreground border-b border-border bg-muted/30">
				{#each COLS as col (col.key)}
					<th class="font-medium px-3 py-2.5 {alignClass[col.align]} {col.hide ?? ''}">
						<button
							class="inline-flex items-center gap-1 hover:text-card-foreground transition-colors"
							onclick={() => onSort(col.key)}
						>
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
			{#each rows as row (row.media_uuid ?? row.anime_uuid)}
				{@const title = resolveTitle(row.title, row.name_eng, row.name_jap, nameLanguage)}
				{@const href = row.media_uuid
					? buildDetailHref('media', row.media_uuid, { from: 'ratings' })
					: buildDetailHref('anime', row.anime_uuid, { from: 'ratings' })}
				<!-- svelte-ignore a11y_click_events_have_key_events a11y_no_static_element_interactions -->
				<tr class="group border-b border-border/60 last:border-0 hover:bg-muted/40 transition-colors cursor-pointer" onclick={(e) => rowClickNavigate(e, href)}>
					<td class="px-3 py-2">
						<a {href} class="text-card-foreground group-hover:text-primary font-medium">{title}</a>
						<span class="ml-1.5 text-xs text-muted-foreground">({row.relationLabel ?? mainSideLabel(row.mainCount, row.sideCount)})</span>
					</td>
					<td class="px-3 py-2 text-right font-bold" style="color: {scoreColor(row.userScore)}">
						{formatDecimalDigits(row.userScore, scoreDecimals)}
					</td>
					<td class="px-3 py-2 text-right text-muted-foreground hidden sm:table-cell">
						{row.malScore !== null ? formatDecimalDigits(row.malScore, 2) : '—'}
					</td>
					<td class="px-3 py-2 text-right font-medium {row.malDelta === null ? 'text-muted-foreground/50' : row.malDelta >= 0 ? 'text-emerald-600' : 'text-rose-600'}">
						{#if row.malDelta === null}—{:else}{row.malDelta >= 0 ? '+' : ''}{formatDecimalDigits(row.malDelta, 2)}{/if}
					</td>
					<td class="px-3 py-2 text-center">
						{#if row.statusBadge === 'dropped'}
							<Badge variant="secondary" class="text-[10px] h-5 {cls.badgeDropped}">Dropped</Badge>
						{:else if row.statusBadge === 'on_hold'}
							<Badge variant="secondary" class="text-[10px] h-5 {cls.badgeOnHold}">On Hold</Badge>
						{:else}
							<span class="text-emerald-600">✓</span>
						{/if}
					</td>
					<td class="px-3 py-2 text-right text-muted-foreground hidden sm:table-cell whitespace-nowrap">
						{formatShortDate(row.modifiedAt)}
					</td>
				</tr>
			{/each}
		</tbody>
	</table>
</div>
