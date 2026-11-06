<script lang="ts">
	/**
	 * Browse's Galaxy tab: the map of every anime (docs/features/galaxy.md), its colourings,
	 * the search's filters lighting up what they keep, finding a title, and a picked star's
	 * nearest neighbours with what they share. The map is the same for every viewer; the
	 * colourings read from the viewer's ratings (`personal`) are inert for a guest.
	 *
	 * The panel keeps a trail of the stars picked since it opened, so a hop to a neighbour
	 * can be walked back; closing it clears the trail. A return from an anime's page lands
	 * on its star again through the back link's `?focus=`; the colouring and the filters
	 * live in `galaxyView`, so they come back too.
	 */
	import { getContext, onMount } from 'svelte';
	import { page } from '$app/state';
	import { ArrowLeft, SlidersHorizontal, X } from 'lucide-svelte';
	import { api, ApiError } from '$lib/api';
	import FilterSheet from '$lib/components/FilterSheet.svelte';
	import GalaxyMap from '$lib/components/GalaxyMap.svelte';
	import { Button } from '$lib/components/ui/button';
	import * as Dialog from '$lib/components/ui/dialog';
	import { Input } from '$lib/components/ui/input';
	import { Label } from '$lib/components/ui/label';
	import { galaxyView } from '$lib/stores/galaxyView';
	import { ensureRatingCoverage, ratedScores, ratedStates, ratingCoverage } from '$lib/stores/ratingCoverage';
	import { addOptimisticJob, bumpJobsRefresh } from '$lib/stores/jobs';
	import { pushToast } from '$lib/stores/toast';
	import { userSettings } from '$lib/stores/userSettings';
	import * as cls from '$lib/styles/classes';
	import type { GalaxyMap as GalaxyMapData, GalaxyNeighbour, GalaxyShared, GalaxyStar } from '$lib/types/api';
	import { formatShortDate, resolveTitle } from '$lib/utils/formatString';
	import { NO_VALUE, SCORE_RAMP, blankColour, mineColour, personal, starFigures, type GalaxyColour } from '$lib/utils/galaxy';
	import { COVERAGE_STYLE } from '$lib/utils/ratingCoverage';
	import { buildDetailHref } from '$lib/utils/navigation';
	import { consumeFocus } from '$lib/utils/scrollFocus';
	import { fetchAnimeSearchResults, fetchMatchingAnimeUuids, filterChips } from '$lib/utils/search';

	const getUserRole = getContext<() => string | null>('userRole');
	let isGuest = $derived(getUserRole?.() === 'restricted_user');
	let isAdmin = $derived(getUserRole?.() === 'admin');
	let nameLanguage = $derived($userSettings?.name_language ?? 'english');

	let map = $state<GalaxyMapData | null>(null);
	let error = $state('');
	let colour = $derived($galaxyView.colour);
	let filters = $derived($galaxyView.filters);
	let filterCount = $derived(filterChips(filters, 'anime').length);
	let sheetOpen = $state(false);
	/** What the filters keep; null with no filters, or when asking for it failed. */
	let lit = $state<Set<string> | null>(null);
	let litFailed = $state(false);
	let selected = $state<string | null>(null);
	let neighbours = $state<GalaxyNeighbour[]>([]);
	let hovered = $state<string | null>(null);
	/** The stars picked before this one, oldest first. */
	let trail = $state<string[]>([]);
	let panel = $state<HTMLElement | null>(null);

	const COLOURS: { value: GalaxyColour; label: string }[] = [
		{ value: 'sector', label: 'Sectors' },
		{ value: 'score', label: 'MAL score' },
		{ value: 'mine', label: 'My progress' },
		{ value: 'own', label: 'My scores' }
	];
	let ratingStep = $derived(Number($userSettings?.rating_step ?? '0.5'));

	let starByUuid = $derived(new Map(map?.stars.map((s) => [s.anime_uuid, s])));
	let star = $derived(selected ? starByUuid.get(selected) : undefined);
	let previous = $derived(trail.length ? starByUuid.get(trail[trail.length - 1]) : undefined);
	let sectorName = $derived(new Map(map?.sectors.map((g) => [g.number, g.name])));
	let regionName = $derived(new Map(map?.regions.map((g) => [g.number, g.name])));
	const title = (s: { title: string; name_eng: string | null; name_jap: string | null }) =>
		resolveTitle(s.title, s.name_eng, s.name_jap, nameLanguage);

	// Asked again whenever the filters change; a late answer for older ones is dropped.
	$effect(() => {
		const asked = filters;
		litFailed = false;
		if (!filterCount) {
			lit = null;
			return;
		}
		fetchMatchingAnimeUuids(asked).then(
			(uuids) => {
				if (filters === asked) lit = new Set(uuids);
			},
			() => {
				if (filters !== asked) return;
				lit = null;
				litFailed = true;
			}
		);
	});

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

	/** A format as "Mostly …" words it. */
	const FORMAT_PLURAL: Record<string, string> = {
		TVSpecial: 'TV specials', Movie: 'movies', OVA: 'OVAs', ONA: 'ONAs', Special: 'specials'
	};

	/** The backend ranks and cuts what a neighbour shares; this only words it. */
	const SHARED_LABEL: Record<GalaxyShared['kind'], (s: GalaxyShared) => string> = {
		synopsis: (s) => `Top ${Math.max(1, Math.round(s.chance * 100))}% synopsis similarity`,
		genre: (s) => s.name!,
		studio: (s) => `Studio: ${s.name}`,
		source: (s) => `Source: ${s.name}`,
		format: (s) => `Mostly ${FORMAT_PLURAL[s.name!] ?? s.name}`
	};

	// Type-to-confirm (rules/frontend.md).
	const getUsername = getContext<() => string | null>('username');
	let username = $derived(getUsername?.() ?? '');
	let rebuildOpen = $state(false);
	let rebuildConfirm = $state('');
	let rebuilding = $state(false);
	async function rebuild() {
		if (rebuildConfirm !== username) return;
		rebuilding = true;
		try {
			const { job_uuid } = await api.post<{ job_uuid: string }>('/admin/galaxy/rebuild', { confirm: rebuildConfirm });
			// Seeds the bell until its next /jobs/mine fetch brings the real row.
			addOptimisticJob({
				uuid: job_uuid, kind: 'galaxy_rebuild', version: 1, status: 'queued', payload: {}, stage: null,
				items_total: null, items_done: 0, result_summary: null, error_message: null,
				created_at: new Date().toISOString(), started_at: null, finished_at: null
			});
			bumpJobsRefresh();
			rebuildOpen = false;
			pushToast('Map rebuild queued. The new map shows on your next visit.');
		} catch (e) {
			pushToast(e instanceof ApiError ? e.detail : 'Failed to queue the rebuild.');
		} finally {
			rebuilding = false;
		}
	}

	let mineCounts = $derived.by(() => {
		const c = { none: 0, some: 0, main: 0, all: 0 };
		for (const s of map?.stars ?? []) if (!lit || lit.has(s.anime_uuid)) c[$ratingCoverage.get(s.anime_uuid) ?? 'none']++;
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
				{@const inert = personal(c.value) && isGuest}
				<button
					type="button"
					aria-pressed={colour === c.value}
					disabled={inert}
					title={inert ? 'Your ratings colour the map once you have an account' : undefined}
					class="{cls.pagePill} {colour === c.value ? cls.pagePillOn : cls.pagePillOff} disabled:opacity-40"
					onclick={() => galaxyView.update((v) => ({ ...v, colour: c.value }))}
				>
					{c.label}
				</button>
			{/each}
			<button
				type="button"
				class="relative inline-flex items-center gap-1.5 {cls.pagePill} {filterCount ? cls.pagePillOn : cls.pagePillOff}"
				onclick={() => (sheetOpen = true)}
			>
				<SlidersHorizontal class="size-4" /> Filters
				{#if filterCount}<span class={cls.countBadge}>{filterCount}</span>{/if}
			</button>
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

		{#if litFailed}
			<p class="text-xs text-white/70">The filters could not be applied to the map.</p>
		{:else if lit}
			<p class="inline-flex items-center gap-1.5 text-xs text-white/70">
				{lit.size} anime match the filters; the rest are greyed out {@render dot(NO_VALUE)}
			</p>
		{/if}

		<div class="flex flex-wrap items-center gap-x-4 gap-y-1 text-xs text-white/70">
			{#if colour === 'sector'}
				<span>Colour only tells neighbouring sectors apart. Faded stars sit between regions; hollow ones joined after the map was fitted.</span>
			{:else}
				{#if colour !== 'mine'}
					<span class="tabular-nums">Top 100%</span>
					<span class="h-2 w-28 rounded-full" style="background:linear-gradient(90deg,{SCORE_RAMP.join(',')})"></span>
					<span class="tabular-nums">Top 1%</span>
				{/if}
				{#if colour === 'score'}
					<span class="inline-flex items-center gap-1.5">{@render dot(blankColour('score', lit != null))} unscored</span>
				{:else}
					<span class="inline-flex items-center gap-1.5">{@render dot(blankColour(colour, lit != null))} Not rated {mineCounts.none}</span>
					{#if colour === 'mine'}
						<span class="inline-flex items-center gap-1.5">
							{@render dot(mineColour('some'))} In progress, on hold, dropped {mineCounts.some}
						</span>
						<span class="inline-flex items-center gap-1.5">{@render dot(mineColour('main'))} Main done {mineCounts.main}</span>
						<span class="inline-flex items-center gap-1.5">
							{@render dot(mineColour('all'), COVERAGE_STYLE.all.hairline)} All done {mineCounts.all}
						</span>
					{/if}
					<span>Dim names: nothing rated there yet.</span>
				{/if}
			{/if}
		</div>

		<div class="gap-4 lg:grid lg:grid-cols-[minmax(0,1fr)_20rem]">
			<GalaxyMap
				{map}
				{colour}
				{lit}
				states={$ratedStates}
				scores={$ratedScores}
				{ratingStep}
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
				<button
					type="button"
					class="{cls.pagePill} {cls.pagePillOff}"
					onclick={() => {
						rebuildConfirm = '';
						rebuildOpen = true;
					}}
				>
					Rebuild map
				</button>
			</div>
			<Dialog.Root bind:open={rebuildOpen}>
				<Dialog.Content class="sm:max-w-md">
					<Dialog.Header>
						<Dialog.Title class="text-destructive">Rebuild the map</Dialog.Title>
						<Dialog.Description>
							The new fit replaces the live map whole: stars move, and sectors and regions may split,
							merge or change names. Hand names carry over to the groups that keep most of their
							stars. The current layout cannot be brought back.
						</Dialog.Description>
					</Dialog.Header>
					<div class="min-w-0 space-y-1.5">
						<!-- One span: Label is a flex row (DeleteCandidatesCard says why). -->
						<Label for="galaxy-rebuild-confirm" class="text-sm">
							<span>Type your admin username (<strong>{username}</strong>) to confirm.</span>
						</Label>
						<Input
							id="galaxy-rebuild-confirm"
							bind:value={rebuildConfirm}
							placeholder={username}
							disabled={!username || rebuilding}
							onkeydown={(e) => e.key === 'Enter' && rebuild()}
						/>
					</div>
					<Dialog.Footer>
						<Button variant="secondary" onclick={() => (rebuildOpen = false)} disabled={rebuilding}>Cancel</Button>
						<Button variant="destructive" onclick={rebuild} disabled={rebuilding || !username || rebuildConfirm !== username}>
							{rebuilding ? 'Queueing…' : 'Rebuild'}
						</Button>
					</Dialog.Footer>
				</Dialog.Content>
			</Dialog.Root>
		{/if}
	</div>
{/if}

<!-- The sheet hands back a fresh object every time; an unchanged set would re-ask and redraw. -->
<FilterSheet
	viewType="anime"
	applied={filters}
	bind:open={sheetOpen}
	onApply={(f) => JSON.stringify(f) !== JSON.stringify(filters) && galaxyView.update((v) => ({ ...v, filters: f }))}
/>
