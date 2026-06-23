<script lang="ts">
	import { ArrowUp, ArrowDown } from 'lucide-svelte';
	import { Badge } from '$lib/components/ui/badge';
	import { scoreColor } from '$lib/utils/chartColors';
	import { formatDecimalDigits, formatShortDate, resolveTitle } from '$lib/utils/formatString';
	import { buildDetailHref } from '$lib/utils/navigation';
	import * as cls from '$lib/styles/classes';
	import type { AnimeRatingRow, SortKey } from '$lib/utils/ratingStats';

	interface Props {
		rows: AnimeRatingRow[];
		nameLanguage: 'english' | 'japanese' | 'romaji';
		scoreDecimals: number;
		sort: SortKey;
		sortDir: 'asc' | 'desc';
		onSort: (key: SortKey) => void;
	}

	let { rows, nameLanguage, scoreDecimals, sort, sortDir, onSort }: Props = $props();

	// Header sort caret — `key` is the column's sort key (null = non-sortable col).
	const sortable = 'inline-flex items-center gap-1 hover:text-card-foreground transition-colors';
</script>

<!-- Table lives on a light card surface, so all text is card/muted-foreground (never white). -->
<div class="overflow-x-auto rounded-xl border border-border {cls.cardGlass}">
	<table class="w-full text-sm">
		<thead>
			<tr class="text-muted-foreground border-b border-border bg-muted/30">
				<th class="text-left font-medium px-3 py-2.5">
					<button class={sortable} onclick={() => onSort('title')}>
						Title
						{#if sort === 'title'}{#if sortDir === 'asc'}<ArrowUp class="size-3" />{:else}<ArrowDown class="size-3" />{/if}{/if}
					</button>
				</th>
				<th class="text-right font-medium px-3 py-2.5">
					<button class={sortable} onclick={() => onSort('score')}>
						Your
						{#if sort === 'score'}{#if sortDir === 'asc'}<ArrowUp class="size-3" />{:else}<ArrowDown class="size-3" />{/if}{/if}
					</button>
				</th>
				<th class="text-right font-medium px-3 py-2.5 hidden sm:table-cell">MAL</th>
				<th class="text-right font-medium px-3 py-2.5">
					<button class={sortable} onclick={() => onSort('malDelta')}>
						Δ
						{#if sort === 'malDelta'}{#if sortDir === 'asc'}<ArrowUp class="size-3" />{:else}<ArrowDown class="size-3" />{/if}{/if}
					</button>
				</th>
				<th class="text-left font-medium px-3 py-2.5 hidden md:table-cell">Genres</th>
				<th class="text-center font-medium px-3 py-2.5">Status</th>
				<th class="text-right font-medium px-3 py-2.5 hidden sm:table-cell">
					<button class={sortable} onclick={() => onSort('date')}>
						Rated
						{#if sort === 'date'}{#if sortDir === 'asc'}<ArrowUp class="size-3" />{:else}<ArrowDown class="size-3" />{/if}{/if}
					</button>
				</th>
			</tr>
		</thead>
		<tbody>
			{#each rows as row (row.anime_uuid)}
				{@const title = resolveTitle(row.title, row.name_eng, row.name_jap, nameLanguage)}
				<tr class="border-b border-border/60 last:border-0 hover:bg-muted/40 transition-colors">
					<td class="px-3 py-2">
						<a href={buildDetailHref('anime', row.anime_uuid, { from: 'ratings' })} class="text-card-foreground hover:text-primary font-medium">
							{title}
						</a>
						{#if row.ratedMediaCount > 1}
							<span class="ml-1.5 text-xs text-muted-foreground">({row.ratedMediaCount})</span>
						{/if}
					</td>
					<td class="px-3 py-2 text-right font-bold" style="color: {scoreColor(row.userScore)}">
						{formatDecimalDigits(row.userScore, scoreDecimals)}
					</td>
					<td class="px-3 py-2 text-right text-muted-foreground hidden sm:table-cell">
						{row.malScore !== null ? formatDecimalDigits(row.malScore, 2) : '—'}
					</td>
					<td class="px-3 py-2 text-right font-medium {row.malDelta === null ? 'text-muted-foreground/50' : row.malDelta >= 0 ? 'text-emerald-600' : 'text-rose-600'}">
						{#if row.malDelta === null}—{:else}{row.malDelta >= 0 ? '+' : ''}{formatDecimalDigits(row.malDelta, 1)}{/if}
					</td>
					<td class="px-3 py-2 hidden md:table-cell">
						<div class="flex flex-wrap gap-1">
							{#each row.genres.slice(0, 3) as g}
								<Badge variant="secondary" class={cls.badgeGenre}>{g}</Badge>
							{/each}
							{#if row.genres.length > 3}
								<span class="text-xs text-muted-foreground self-center">+{row.genres.length - 3}</span>
							{/if}
						</div>
					</td>
					<td class="px-3 py-2 text-center">
						{#if row.statusBadge === 'dropped'}
							<Badge variant="destructive" class="text-[10px] h-5">Dropped</Badge>
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
