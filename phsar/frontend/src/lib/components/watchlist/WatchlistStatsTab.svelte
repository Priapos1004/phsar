<script lang="ts">
	import { onMount } from 'svelte';
	import * as Card from '$lib/components/ui/card';
	import Tooltip from '$lib/components/Tooltip.svelte';
	import TagBarLabel from '$lib/components/TagBarLabel.svelte';
	import { Film, Layers, Clock, Star, TrendingUp } from 'lucide-svelte';
	import type { TagCount, WatchlistSummary } from '$lib/utils/watchlistStats';
	import { getThemedChartColorPalette } from '$lib/utils/chartColors';
	import { formatDurationCompact } from '$lib/utils/formatString';
	import { mainSideLabel } from '$lib/utils/relations';
	import { ensureGenresLoaded } from '$lib/stores/genres';
	import * as cls from '$lib/styles/classes';

	// Presentational — the /watchlist page owns the /ratings/scores fetch and computes the
	// summary once (so grid <-> stats toggling doesn't refetch/recompute). This tab just
	// renders it; mounting on demand replays the bar grow-in.
	interface Props {
		summary: WatchlistSummary | null;
		loading: boolean;
		hasItems: boolean;
	}

	let { summary, loading, hasItems }: Props = $props();

	let grown = $state(false); // flips true once the summary is in so the bars grow in from 0

	onMount(() => {
		ensureGenresLoaded(); // genre descriptions for the label tooltips
	});

	// Flip `grown` one frame after the summary first appears so the width transition plays
	// 0 -> pct (works whether the summary is already present at mount or arrives later).
	$effect(() => {
		if (summary && !grown) requestAnimationFrame(() => (grown = true));
	});

	const palette = getThemedChartColorPalette();
	const barPct = (c: TagCount, max: number) => (max > 0 ? (c.count / max) * 100 : 0);

	// Bar hover: the media (not anime) main/side split + the queued runtime for that tag.
	// Format matches the app convention (e.g. ratings stats): "15 main · 15 side · 5d 5h".
	const barHover = (t: TagCount): string =>
		t.seconds > 0 ? `${mainSideLabel(t.main, t.side)} · ${formatDurationCompact(t.seconds)}` : mainSideLabel(t.main, t.side);

	// Headline tiles: an accent-tinted icon chip + the figure. Accent hues from the themed
	// chart palette so they track the active theme.
	let tiles = $derived(
		summary
			? [
					{ label: 'Anime', value: summary.totalAnime as number | string, icon: Film, color: palette[0], hint: null as string | null },
					{ label: 'Media', value: summary.totalMedia, icon: Layers, color: palette[1], hint: null },
					{ label: 'Queued time', value: formatDurationCompact(summary.totalQueuedSeconds), icon: Clock, color: palette[2], hint: 'Total runtime of everything on your watchlist (episodes × length).' },
					{ label: 'Already rated', value: summary.alreadyRated, icon: Star, color: palette[3], hint: "Watchlisted media you've already rated." },
					{ label: 'Continuations', value: summary.continuations, icon: TrendingUp, color: palette[4], hint: "Watchlisted media whose anime you've already rated another entry of — you're mid-franchise." },
				]
			: [],
	);
</script>

{#if !hasItems}
	<div class="py-12 text-center space-y-2">
		<p class="text-white/70">Nothing on your watchlist yet.</p>
		<p class="text-white/50 text-sm">Bookmark anime and media to see your watchlist stats here.</p>
	</div>
{:else if loading}
	<div class="py-12 text-center text-white/60">Loading statistics…</div>
{:else if summary}
	{@const s = summary}
	<div class="space-y-4">
		<!-- Headline tiles -->
		<div class="grid grid-cols-2 sm:grid-cols-3 lg:grid-cols-5 gap-3">
			{#each tiles as t (t.label)}
				{@const Icon = t.icon}
				<Card.Root class={cls.cardGlass}>
					<Card.Content class="py-4 flex items-center gap-3">
						<div class="size-11 shrink-0 rounded-xl flex items-center justify-center" style="background:color-mix(in srgb, {t.color} 15%, transparent); color:{t.color}">
							<Icon class="size-5" />
						</div>
						<div class="min-w-0">
							<div class="text-2xl font-bold text-card-foreground tabular-nums leading-tight">{t.value}</div>
							{#if t.hint}
								<Tooltip text={t.hint}>
									<span class="text-xs uppercase tracking-wide text-muted-foreground cursor-help border-b border-dotted border-muted-foreground/40">{t.label}</span>
								</Tooltip>
							{:else}
								<span class="text-xs uppercase tracking-wide text-muted-foreground">{t.label}</span>
							{/if}
						</div>
					</Card.Content>
				</Card.Root>
			{/each}
		</div>

		<!-- Top genres / studios — symmetric top-5, palette-colored bars that grow in. -->
		<div class="grid gap-3 md:grid-cols-2">
			{@render tagBars('Top genres', s.topGenres, 'genre')}
			{@render tagBars('Top studios', s.topStudios, 'studio')}
		</div>
	</div>
{/if}

{#snippet tagBars(title: string, tags: TagCount[], kind: 'genre' | 'studio')}
	<Card.Root class={cls.cardGlass}>
		<Card.Content class="space-y-3">
			<div>
				<h3 class="text-base font-semibold text-card-foreground">{title}</h3>
				<!-- Explicit metric caption: the bar length + count are the number of ANIME
				     (not media) carrying each genre/studio; the media split is in the hover. -->
				<p class="text-xs text-muted-foreground">Anime per {kind}</p>
			</div>
			{#if tags.length === 0}
				<p class="text-sm text-muted-foreground">No {kind === 'genre' ? 'genres' : 'studios'} yet.</p>
			{:else}
				{@const max = tags[0].count}
				<div class="space-y-2.5">
					{#each tags as t, i (t.name)}
						<div class="flex items-center gap-3">
							<div class="w-32 shrink-0 min-w-0 flex items-center justify-start text-sm">
								<TagBarLabel name={t.name} {kind} />
							</div>
							<!-- Themed app Tooltip (the intentional-hint path — matches the genre label
							     tooltip in the same row): the media main/side split + queued runtime
							     behind this anime-count bar. Track styling lives on the trigger span. -->
							<Tooltip text={barHover(t)} class="flex-grow h-2.5 rounded-full bg-muted overflow-hidden">
								<span
									class="block h-full rounded-full transition-[width] duration-700 ease-out"
									style="width:{grown ? barPct(t, max) : 0}%; background:{palette[i % palette.length]}"
								></span>
							</Tooltip>
							<span class="w-6 shrink-0 text-right text-sm text-muted-foreground tabular-nums">{t.count}</span>
						</div>
					{/each}
				</div>
			{/if}
		</Card.Content>
	</Card.Root>
{/snippet}
