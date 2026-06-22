<script lang="ts">
	import { onMount } from 'svelte';
	import { api, ApiError } from '$lib/api';
	import { Button } from '$lib/components/ui/button';
	import * as Card from '$lib/components/ui/card';
	import * as Select from '$lib/components/ui/select';
	import { Input } from '$lib/components/ui/input';
	import Tooltip from '$lib/components/Tooltip.svelte';
	import { CheckCircle2, RefreshCw, Search, X } from 'lucide-svelte';
	import { fetchAnimeSearchResults } from '$lib/utils/search';
	import { resolveTitle, formatShortDate } from '$lib/utils/formatString';
	import { buildDetailHref } from '$lib/utils/navigation';
	import { userSettings } from '$lib/stores/userSettings';
	import type { AnimeSearchResult, FinishedAnimeItem } from '$lib/types/api';

	let finished = $state<FinishedAnimeItem[]>([]);
	// `loading` flips off after the first fetch and stays off; later fetches only
	// toggle `refreshing` so the keyed list diffs in place (mirrors MergeCandidatesCard).
	let loading = $state(true);
	let refreshing = $state(false);
	let error = $state('');
	let busyUuid = $state<string | null>(null);

	let query = $state('');
	let results = $state<AnimeSearchResult[]>([]);
	let searching = $state(false);
	let debounceTimer: ReturnType<typeof setTimeout> | undefined;

	type SortKey = 'newest' | 'oldest' | 'title';
	const SORT_OPTIONS: { value: SortKey; label: string }[] = [
		{ value: 'newest', label: 'Newest marked' },
		{ value: 'oldest', label: 'Oldest marked' },
		{ value: 'title', label: 'Title A–Z' },
	];
	let sortKey = $state<SortKey>('newest');

	let nameLanguage = $derived($userSettings?.name_language ?? 'english');
	let finishedUuids = $derived(new Set(finished.map((a) => a.uuid)));
	let sortLabel = $derived(SORT_OPTIONS.find((o) => o.value === sortKey)?.label ?? '');

	function title(a: { title: string; name_eng: string | null; name_jap: string | null }): string {
		return resolveTitle(a.title, a.name_eng, a.name_jap, nameLanguage);
	}

	let sortedFinished = $derived.by(() => {
		const arr = [...finished];
		if (sortKey === 'title') return arr.sort((a, b) => title(a).localeCompare(title(b)));
		// marked_at is ISO-8601, so string compare is chronological
		return arr.sort((a, b) =>
			sortKey === 'newest' ? b.marked_at.localeCompare(a.marked_at) : a.marked_at.localeCompare(b.marked_at),
		);
	});

	onMount(async () => {
		await fetchFinished();
		loading = false;
	});

	async function fetchFinished() {
		refreshing = true;
		error = '';
		try {
			finished = await api.get<FinishedAnimeItem[]>('/admin/finished-anime');
		} catch (err) {
			error = err instanceof ApiError ? err.detail : 'Failed to load finished anime';
		} finally {
			refreshing = false;
		}
	}

	function onQueryInput() {
		clearTimeout(debounceTimer);
		const q = query.trim();
		if (!q) {
			results = [];
			return;
		}
		debounceTimer = setTimeout(() => runSearch(q), 300);
	}

	function clearSearch() {
		clearTimeout(debounceTimer);
		query = '';
		results = [];
	}

	async function runSearch(q: string) {
		searching = true;
		error = '';
		try {
			results = await fetchAnimeSearchResults({ query: q, search_type: 'title', view_type: 'anime' });
		} catch (err) {
			error = err instanceof ApiError ? err.detail : 'Search failed';
		} finally {
			searching = false;
		}
	}

	async function mark(uuid: string) {
		busyUuid = uuid;
		error = '';
		try {
			await api.post(`/admin/finished-anime/${uuid}`, {});
			// Clear + close the search so marking feels like a committed selection.
			query = '';
			results = [];
			await fetchFinished();
		} catch (err) {
			error = err instanceof ApiError ? err.detail : 'Failed to mark complete';
		} finally {
			busyUuid = null;
		}
	}

	async function unmark(uuid: string) {
		busyUuid = uuid;
		error = '';
		try {
			await api.del(`/admin/finished-anime/${uuid}`);
			await fetchFinished();
		} catch (err) {
			error = err instanceof ApiError ? err.detail : 'Failed to remove flag';
		} finally {
			busyUuid = null;
		}
	}
</script>

{#snippet cover(src: string | null, alt: string)}
	{#if src}
		<img {src} {alt} class="w-9 h-12 rounded object-cover shrink-0 bg-muted" loading="lazy" />
	{:else}
		<div class="w-9 h-12 rounded bg-muted shrink-0 flex items-center justify-center">
			<CheckCircle2 class="size-4 text-muted-foreground/40" />
		</div>
	{/if}
{/snippet}

<Card.Root>
	<Card.Header>
		<div class="flex items-center justify-between gap-2">
			<div>
				<Card.Title class="flex items-center gap-2">
					<CheckCircle2 class="size-5 text-emerald-600" />
					Story Completion
					<span class="rounded-full bg-emerald-100 text-emerald-800 text-xs font-semibold px-2 py-0.5">
						{finished.length}
					</span>
				</Card.Title>
				<Card.Description>
					Mark an anime as story-complete when its narrative has concluded — distinct from "Finished
					Airing", which only means episodes stopped broadcasting.
				</Card.Description>
			</div>
			<Tooltip text="Refresh">
				{#snippet trigger(props)}
					<Button {...props} variant="ghost" size="icon" onclick={fetchFinished} disabled={loading || refreshing} aria-label="Refresh">
						<RefreshCw class="size-4 {refreshing ? 'animate-spin' : ''}" />
					</Button>
				{/snippet}
			</Tooltip>
		</div>
	</Card.Header>
	<Card.Content class="space-y-4">
		<!-- Search to mark a new anime -->
		<div class="space-y-2">
			<div class="relative">
				<Search class="absolute left-2.5 top-1/2 -translate-y-1/2 size-4 text-muted-foreground" />
				<Input
					class="pl-8 pr-8"
					placeholder="Search anime to mark complete…"
					bind:value={query}
					oninput={onQueryInput}
				/>
				{#if query}
					<button
						type="button"
						onclick={clearSearch}
						aria-label="Clear search"
						class="absolute right-2 top-1/2 -translate-y-1/2 text-muted-foreground hover:text-card-foreground"
					>
						<X class="size-4" />
					</button>
				{/if}
			</div>
			{#if query.trim() && !searching}
				<div class="rounded-lg border border-border divide-y divide-border max-h-72 overflow-y-auto">
					{#each results as r (r.uuid)}
						<div class="flex items-center gap-3 px-3 py-2">
							{@render cover(r.cover_image, title(r))}
							<a
								href={buildDetailHref('anime', r.uuid, { from: 'completion' })}
								class="text-sm hover:underline truncate flex-1 min-w-0"
								title={title(r)}
							>
								{title(r)}
							</a>
							{#if finishedUuids.has(r.uuid)}
								<span class="inline-flex items-center gap-1 text-xs text-emerald-600 shrink-0">
									<CheckCircle2 class="size-3.5" /> Marked
								</span>
							{:else}
								<Button size="sm" variant="secondary" onclick={() => mark(r.uuid)} disabled={busyUuid === r.uuid}>
									Mark complete
								</Button>
							{/if}
						</div>
					{:else}
						<p class="px-3 py-2 text-sm text-muted-foreground">No matching anime.</p>
					{/each}
				</div>
			{/if}
		</div>

		{#if error}
			<p class="text-destructive text-sm">{error}</p>
		{/if}

		<!-- Currently-marked list -->
		{#if loading}
			<p class="text-sm text-muted-foreground">Loading…</p>
		{:else if finished.length === 0}
			<p class="text-sm text-muted-foreground">No anime marked story-complete yet. Search above to add one.</p>
		{:else}
			<div class="flex items-center justify-between gap-2">
				<span class="text-xs font-medium text-muted-foreground uppercase tracking-wide">Marked anime</span>
				<Select.Root type="single" bind:value={sortKey}>
					<Select.Trigger class="h-8 w-[140px] text-xs">{sortLabel}</Select.Trigger>
					<Select.Content>
						{#each SORT_OPTIONS as o}
							<Select.Item value={o.value}>{o.label}</Select.Item>
						{/each}
					</Select.Content>
				</Select.Root>
			</div>
			<div class="rounded-lg border border-border divide-y divide-border">
				{#each sortedFinished as a (a.uuid)}
					<div class="flex items-center gap-3 px-3 py-2">
						{@render cover(a.cover_image, title(a))}
						<div class="flex-1 min-w-0">
							<a
								href={buildDetailHref('anime', a.uuid, { from: 'completion' })}
								class="text-sm font-medium text-card-foreground hover:underline truncate block"
								title={title(a)}
							>
								{title(a)}
							</a>
							<p class="text-xs text-muted-foreground truncate">
								Marked {formatShortDate(a.marked_at)}{a.marked_by_username ? ` by ${a.marked_by_username}` : ''}
							</p>
						</div>
						<Tooltip text="Remove story-complete flag">
							{#snippet trigger(props)}
								<Button {...props} size="icon" variant="ghost" onclick={() => unmark(a.uuid)} disabled={busyUuid === a.uuid} aria-label="Remove story-complete flag">
									<X class="size-4" />
								</Button>
							{/snippet}
						</Tooltip>
					</div>
				{/each}
			</div>
		{/if}
	</Card.Content>
</Card.Root>
