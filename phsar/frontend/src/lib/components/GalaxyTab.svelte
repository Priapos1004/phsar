<script lang="ts">
	/**
	 * Browse's Galaxy tab: the map of every anime (docs/features/galaxy.md), its colourings,
	 * a genre to light up, finding a title, and a picked star's nearest neighbours with
	 * what they share. The map is the same for every viewer; My ratings is personal, so a
	 * guest sees it inert.
	 *
	 * The panel keeps a trail of the stars picked since it opened, so a hop to a neighbour
	 * can be walked back; closing it clears the trail. A return from an anime's page lands
	 * on its star again through the back link's `?focus=`.
	 */
	import { getContext, onMount } from 'svelte';
	import { page } from '$app/state';
	import { ArrowLeft, X } from 'lucide-svelte';
	import { api, ApiError } from '$lib/api';
	import GalaxyMap from '$lib/components/GalaxyMap.svelte';
	import { Input } from '$lib/components/ui/input';
	import * as Select from '$lib/components/ui/select';
	import { ensureRatingCoverage, ratedStates, ratingCoverage } from '$lib/stores/ratingCoverage';
	import { addOptimisticJob, bumpJobsRefresh } from '$lib/stores/jobs';
	import { pushToast } from '$lib/stores/toast';
	import { userSettings } from '$lib/stores/userSettings';
	import * as cls from '$lib/styles/classes';
	import type { GalaxyMap as GalaxyMapData, GalaxyNeighbour, GalaxyShared, GalaxyStar } from '$lib/types/api';
	import { formatShortDate, resolveTitle } from '$lib/utils/formatString';
	import { NO_VALUE, SCORE_RAMP, mineColour, starFigures, type GalaxyColour } from '$lib/utils/galaxy';
	import { COVERAGE_STYLE } from '$lib/utils/ratingCoverage';
	import { buildDetailHref } from '$lib/utils/navigation';
	import { consumeFocus } from '$lib/utils/scrollFocus';
	import { fetchAnimeSearchResults } from '$lib/utils/search';

	const getUserRole = getContext<() => string | null>('userRole');
	let isGuest = $derived(getUserRole?.() === 'restricted_user');
	let isAdmin = $derived(getUserRole?.() === 'admin');
	let nameLanguage = $derived($userSettings?.name_language ?? 'english');

	let map = $state<GalaxyMapData | null>(null);
	let error = $state('');
	let colour = $state<GalaxyColour>('sector');
	let tag = $state('');
	let selected = $state<string | null>(null);
	let neighbours = $state<GalaxyNeighbour[]>([]);
	let hovered = $state<string | null>(null);
	/** The stars picked before this one, oldest first. */
	let trail = $state<string[]>([]);
	let panel = $state<HTMLElement | null>(null);

	const COLOURS: { value: GalaxyColour; label: string }[] = [
		{ value: 'sector', label: 'Sectors' },
		{ value: 'score', label: 'MAL score' },
		{ value: 'mine', label: 'My ratings' }
	];

	let starByUuid = $derived(new Map(map?.stars.map((s) => [s.anime_uuid, s])));
	let star = $derived(selected ? starByUuid.get(selected) : undefined);
	let previous = $derived(trail.length ? starByUuid.get(trail[trail.length - 1]) : undefined);
	let sectorName = $derived(new Map(map?.sectors.map((g) => [g.number, g.name])));
	let regionName = $derived(new Map(map?.regions.map((g) => [g.number, g.name])));
	let genres = $derived.by(() => {
		const count = new Map<string, number>();
		for (const s of map?.stars ?? []) for (const g of s.genres) count.set(g, (count.get(g) ?? 0) + 1);
		return [...count].sort(([a], [b]) => a.localeCompare(b, undefined, { sensitivity: 'base' }));
	});
	const title = (s: { title: string; name_eng: string | null; name_jap: string | null }) =>
		resolveTitle(s.title, s.name_eng, s.name_jap, nameLanguage);

	onMount(async () => {
		const returnedTo = consumeFocus(page.url);
		if (!isGuest) void ensureRatingCoverage();
		try {
			map = await api.get<GalaxyMapData>('/browse/galaxy');
		} catch (e) {
			error = e instanceof ApiError ? e.detail : 'Failed to load the map.';
			return;
		}
		if (returnedTo && starByUuid.has(returnedTo)) void load(returnedTo);
	});

	/** The panel's content is about to swap: a focused control inside it would vanish
	 *  under the keyboard, so focus moves to the panel itself first. */
	function keepFocus() {
		if (panel?.contains(document.activeElement)) panel.focus({ preventScroll: true });
	}

	async function load(uuid: string) {
		keepFocus();
		selected = uuid;
		neighbours = [];
		hovered = null;
		try {
			const found = await api.get<GalaxyNeighbour[]>(`/browse/galaxy/${uuid}/neighbours`);
			// A later pick may have landed first.
			if (selected === uuid) neighbours = found;
		} catch {
			// The panel still shows the star; its neighbours stay empty.
		}
	}

	function pick(uuid: string) {
		if (uuid === selected) return;
		if (selected) trail = [...trail, selected];
		void load(uuid);
	}

	function back() {
		const prev = trail[trail.length - 1];
		trail = trail.slice(0, -1);
		void load(prev);
	}

	function close() {
		keepFocus();
		trail = [];
		selected = null;
		neighbours = [];
		hovered = null;
	}

	// ---- finding a title: the search's own title match, ranked as Search ranks it --------
	let findText = $state('');
	let found = $state<GalaxyStar[]>([]);
	let findOpen = $state(false);
	let findActive = $state(0);
	let findTimer: ReturnType<typeof setTimeout> | undefined;

	function suggest() {
		clearTimeout(findTimer);
		const query = findText.trim();
		if (!query) {
			found = [];
			return;
		}
		findTimer = setTimeout(async () => {
			// An answer counts only while the box still asks it: a later keystroke, a cleared
			// box or a pick all change the text.
			const current = () => findText.trim() === query;
			try {
				const rows = await fetchAnimeSearchResults({ query, search_type: 'title' }, 10);
				if (!current()) return;
				// An anime without a star yet has nowhere to go.
				found = rows.flatMap((r) => starByUuid.get(r.uuid) ?? []).slice(0, 8);
				findActive = 0;
				findOpen = true;
			} catch {
				if (current()) found = [];
			}
		}, 200);
	}

	function choose(s: GalaxyStar) {
		pick(s.anime_uuid);
		findText = '';
		found = [];
	}

	function findKey(e: KeyboardEvent) {
		if ((e.key === 'ArrowDown' || e.key === 'ArrowUp') && found.length) {
			e.preventDefault();
			findOpen = true;
			findActive = (findActive + (e.key === 'ArrowDown' ? 1 : found.length - 1)) % found.length;
		} else if (e.key === 'Enter' && found[findActive]) {
			e.preventDefault();
			choose(found[findActive]);
		} else if (e.key === 'Escape') {
			findOpen = false;
		}
	}

	/** The backend ranks and cuts what a neighbour shares; this only words it. */
	const SHARED_LABEL: Record<GalaxyShared['kind'], (s: GalaxyShared) => string> = {
		synopsis: (s) => `Top ${Math.max(1, Math.round(s.chance * 100))}% synopsis similarity`,
		genre: (s) => s.name!,
		studio: (s) => `Studio: ${s.name}`,
		source: (s) => `Source: ${s.name}`
	};

	let rebuilding = $state(false);
	async function rebuild() {
		rebuilding = true;
		try {
			const { job_uuid } = await api.post<{ job_uuid: string }>('/admin/galaxy/rebuild', {});
			// Seeds the bell until its next /jobs/mine fetch brings the real row.
			addOptimisticJob({
				uuid: job_uuid, kind: 'galaxy_rebuild', version: 1, status: 'queued', payload: {}, stage: null,
				items_total: null, items_done: 0, result_summary: null, error_message: null,
				created_at: new Date().toISOString(), started_at: null, finished_at: null
			});
			bumpJobsRefresh();
			pushToast('Map rebuild queued. The new map shows on your next visit.');
		} catch (e) {
			pushToast(e instanceof ApiError ? e.detail : 'Failed to queue the rebuild.');
		} finally {
			rebuilding = false;
		}
	}

	let mineCounts = $derived.by(() => {
		const c = { none: 0, some: 0, main: 0, all: 0 };
		for (const s of map?.stars ?? []) c[$ratingCoverage.get(s.anime_uuid) ?? 'none']++;
		return c;
	});
</script>

{#snippet dot(color: string, ring?: string)}
	<span class="inline-block size-2.5 shrink-0 rounded-full" style="background:{color};{ring ? `box-shadow:0 0 0 1.5px ${ring}` : ''}"></span>
{/snippet}

{#snippet cover(s: GalaxyStar | GalaxyNeighbour, size: string)}
	{#if s.cover_image}
		<img src={s.cover_image} alt="" loading="lazy" class="{size} shrink-0 rounded-md object-cover" />
	{:else}
		<span class="{size} shrink-0 rounded-md bg-white/10"></span>
	{/if}
{/snippet}

{#if error}
	<p class={cls.noticeCard}>{error}</p>
{:else if !map}
	<div class="h-[70vh] min-h-[420px] animate-pulse rounded-xl border border-white/10 bg-white/5"></div>
{:else if map.stars.length === 0}
	<p class={cls.noticeCard}>The map has not been drawn yet. It appears after the first rebuild.</p>
{:else}
	<div class="space-y-3">
		<div class="flex flex-wrap items-center gap-2">
			{#each COLOURS as c (c.value)}
				{@const inert = c.value === 'mine' && isGuest}
				<button
					type="button"
					aria-pressed={colour === c.value}
					disabled={inert}
					title={inert ? 'Your ratings colour the map once you have an account' : undefined}
					class="{cls.pagePill} {colour === c.value ? cls.pagePillOn : cls.pagePillOff} disabled:opacity-40"
					onclick={() => (colour = c.value)}
				>
					{c.label}
				</button>
			{/each}
			<Select.Root type="single" value={tag} onValueChange={(v) => (tag = v ?? '')}>
				<Select.Trigger size="sm" class={cls.pageControl} aria-label="Light up a genre">
					{tag || 'Light up a genre'}
				</Select.Trigger>
				<Select.Content>
					<Select.Item value="">None</Select.Item>
					{#each genres as [g, n] (g)}
						<Select.Item value={g}>{g} ({n})</Select.Item>
					{/each}
				</Select.Content>
			</Select.Root>
			<div class="relative max-sm:w-full sm:ml-auto sm:w-64">
				<Input
					type="text"
					role="combobox"
					aria-label="Find an anime on the map"
					aria-expanded={findOpen && found.length > 0}
					aria-controls="galaxy-find"
					aria-activedescendant={findOpen && found[findActive] ? `galaxy-find-${findActive}` : undefined}
					aria-autocomplete="list"
					autocomplete="off"
					placeholder="Find an anime"
					class="{cls.pageControl} h-8 px-3 text-sm placeholder:text-white/40"
					bind:value={findText}
					oninput={suggest}
					onkeydown={findKey}
					onfocus={() => (findOpen = true)}
					onblur={() => (findOpen = false)}
				/>
				{#if findOpen && found.length}
					<!-- preventDefault keeps focus in the input, so picking an option never leaves
					     focus on a node the list is about to drop. -->
					<ul id="galaxy-find" role="listbox" class="absolute right-0 left-0 z-50 mt-1 max-h-96 overflow-y-auto rounded-xl border border-border bg-popover py-1 shadow-md">
						{#each found as s, i (s.anime_uuid)}
							<li id="galaxy-find-{i}" role="option" aria-selected={i === findActive}>
								<button
									type="button"
									tabindex="-1"
									class="flex w-full items-center gap-2.5 px-3 py-1.5 text-left text-sm text-popover-foreground hover:bg-accent hover:text-accent-foreground {i === findActive ? 'bg-accent text-accent-foreground' : ''}"
									onmousedown={(e) => (e.preventDefault(), choose(s))}
									onmouseenter={() => (findActive = i)}
								>
									{@render cover(s, 'h-9 w-6')}
									<span class="min-w-0 flex-1 truncate" title={title(s)}>{title(s)}</span>
									{#if s.year}<span class="shrink-0 text-xs text-muted-foreground tabular-nums">{s.year}</span>{/if}
								</button>
							</li>
						{/each}
					</ul>
				{/if}
			</div>
		</div>

		<div class="flex flex-wrap items-center gap-x-4 gap-y-1 text-xs text-white/70">
			{#if tag}
				<span>{genres.find(([g]) => g === tag)?.[1] ?? 0} anime are {tag} by majority; the rest are dimmed.</span>
			{:else if colour === 'score'}
				<span class="tabular-nums">Top 100%</span>
				<span class="h-2 w-28 rounded-full" style="background:linear-gradient(90deg,{SCORE_RAMP.join(',')})"></span>
				<span class="tabular-nums">Top 1%</span>
				<span class="inline-flex items-center gap-1.5">{@render dot(NO_VALUE)} unscored</span>
			{:else if colour === 'mine'}
				<span class="inline-flex items-center gap-1.5">{@render dot(mineColour(undefined))} Not rated {mineCounts.none}</span>
				<span class="inline-flex items-center gap-1.5">
					{@render dot(mineColour('some'))} In progress, on hold, dropped {mineCounts.some}
				</span>
				<span class="inline-flex items-center gap-1.5">{@render dot(mineColour('main'))} Main done {mineCounts.main}</span>
				<span class="inline-flex items-center gap-1.5">
					{@render dot(mineColour('all'), COVERAGE_STYLE.all.hairline)} All done {mineCounts.all}
				</span>
				<span>Dim names: nothing rated there yet.</span>
			{:else}
				<span>Colour only tells neighbouring sectors apart. Faded stars sit between regions; hollow ones joined after the map was fitted.</span>
			{/if}
		</div>

		<div class="gap-4 lg:grid lg:grid-cols-[minmax(0,1fr)_20rem]">
			<GalaxyMap
				{map}
				{colour}
				{tag}
				states={$ratedStates}
				{selected}
				neighbours={neighbours.map((n) => n.anime_uuid)}
				{hovered}
				{nameLanguage}
				onSelect={pick}
			/>

			<aside
				bind:this={panel}
				tabindex="-1"
				aria-label="The picked anime"
				class="mt-4 rounded-xl border border-white/10 bg-white/5 p-4 text-sm text-white outline-none lg:mt-0 lg:max-h-[70vh] lg:overflow-y-auto"
			>
				{#if star}
					<div class="-mt-1 mb-3 flex min-h-8 items-center gap-2">
						{#if previous}
							<button type="button" class="{cls.pageNavLink} min-w-0" onclick={back}>
								<ArrowLeft class="size-4 shrink-0" />
								<span class="truncate" title={title(previous)}>{title(previous)}</span>
							</button>
						{/if}
						<button
							type="button"
							aria-label="Close"
							title="Close"
							class="relative ml-auto rounded-full p-1 text-white/60 hover:bg-white/10 hover:text-white {cls.hitArea}"
							onclick={close}
						>
							<X class="size-4" />
						</button>
					</div>
					{@const href = buildDetailHref('anime', star.anime_uuid, { from: 'galaxy' })}
					<div class="flex gap-3">
						<a {href} class="shrink-0" tabindex="-1" aria-hidden="true">{@render cover(star, 'aspect-[2/3] w-20')}</a>
						<div class="min-w-0">
							<a {href} class="text-base leading-snug font-semibold hover:underline">{title(star)}</a>
							<p class="mt-1 text-white/70 tabular-nums">{starFigures(star)}</p>
							{#if star.genres.length}
								<p class="mt-1 text-xs text-white/60">{star.genres.join(' · ')}</p>
							{/if}
						</div>
					</div>
					<dl class="mt-4 grid grid-cols-[auto_minmax(0,1fr)] gap-x-3 gap-y-1.5 text-xs">
						<dt class="text-white/50">Sector</dt>
						<dd class="text-white/85">{sectorName.get(star.sector)}</dd>
						<dt class="text-white/50">Region</dt>
						<dd class="text-white/85">{regionName.get(star.region)}</dd>
					</dl>
					{#if star.between}
						<p class="mt-1.5 text-xs text-white/50">It sits between regions: none of them claims it clearly.</p>
					{/if}
					<h3 class="mt-5 text-xs font-semibold tracking-wide text-white/50 uppercase">Nearest neighbours</h3>
					<p class="mb-1.5 text-xs text-white/50">Each with what it shares with this one.</p>
					<ol class="-mx-1.5 space-y-0.5">
						{#each neighbours as n (n.anime_uuid)}
							<li>
								<button
									type="button"
									class="flex w-full gap-2.5 rounded-lg p-1.5 text-left hover:bg-white/5 focus-visible:bg-white/5"
									onclick={() => pick(n.anime_uuid)}
									onmouseenter={() => (hovered = n.anime_uuid)}
									onmouseleave={() => (hovered = null)}
									onfocus={() => (hovered = n.anime_uuid)}
									onblur={() => (hovered = null)}
								>
									{@render cover(n, 'h-15 w-10')}
									<span class="min-w-0">
										<span class="block leading-snug font-medium">{title(n)}</span>
										<span class="mt-1 flex flex-wrap gap-1">
											{#each n.shared as s (`${s.kind}:${s.name}`)}
												<span class="rounded-full border border-white/15 px-1.5 py-px text-[11px] text-white/70">{SHARED_LABEL[s.kind](s)}</span>
											{/each}
										</span>
									</span>
								</button>
							</li>
						{/each}
					</ol>
				{:else}
					<p class="text-white/70">Pick a star to see where it sits and its nearest neighbours.</p>
				{/if}
			</aside>
		</div>

		{#if isAdmin}
			<div class="flex flex-wrap items-center justify-between gap-3 rounded-xl border border-white/10 bg-white/5 px-4 py-3 text-sm text-white/70">
				<span>Map fitted {map.fitted_at ? formatShortDate(map.fitted_at) : '—'}. A rebuild refits it from today's catalogue.</span>
				<button type="button" class="{cls.pagePill} {cls.pagePillOff}" disabled={rebuilding} onclick={rebuild}>Rebuild map</button>
			</div>
		{/if}
	</div>
{/if}
