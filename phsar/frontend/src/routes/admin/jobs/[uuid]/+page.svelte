<script lang="ts">
	import { onMount, getContext } from 'svelte';
	import { goto } from '$app/navigation';
	import { page } from '$app/state';
	import { api, ApiError } from '$lib/api';
	import { Input } from '$lib/components/ui/input';
	import * as Card from '$lib/components/ui/card';
	import JobDetailHeader from '$lib/components/admin/JobDetailHeader.svelte';
	import JobDetailCounters from '$lib/components/admin/JobDetailCounters.svelte';
	import MediaChangeCard from '$lib/components/admin/MediaChangeCard.svelte';
	import AnimeUmbrellaCard from '$lib/components/admin/AnimeUmbrellaCard.svelte';
	import Notice from '$lib/components/Notice.svelte';
	import type {
		AdminJobResponse,
		UpdateSweepResultSummary,
		UpdateSweepMediaChange,
	} from '$lib/types/api';

	const getUserRole = getContext<() => string | null>('userRole');

	let uuid = $derived(page.params.uuid as string);
	let job = $state<AdminJobResponse | null>(null);
	let loading = $state(true);
	let error = $state('');

	async function load() {
		loading = true;
		error = '';
		try {
			job = await api.get<AdminJobResponse>(`/admin/jobs/${uuid}`);
		} catch (err) {
			error = err instanceof ApiError ? err.detail : 'Failed to load job';
			job = null;
		} finally {
			loading = false;
		}
	}

	onMount(() => {
		if (getUserRole() !== 'admin') {
			void goto('/');
			return;
		}
		void load();
	});

	// Reload when the route param changes (e.g. clicking a parent-job link).
	$effect(() => {
		if (uuid && job && job.uuid !== uuid) void load();
	});

	type Filter = 'all' | 'dynamic' | 'static' | 'drift';
	let filter = $state<Filter>('all');
	let search = $state('');

	let v2Summary = $derived.by(() => {
		if (!job || job.kind !== 'update_sweep' || job.version < 2) return null;
		return (job.result_summary ?? null) as UpdateSweepResultSummary | null;
	});

	let visibleMediaChanges = $derived.by(() => {
		const all = v2Summary?.media_changes ?? [];
		const q = search.trim().toLowerCase();
		return all.filter((m: UpdateSweepMediaChange) => {
			if (filter === 'dynamic' && m.dynamic.length === 0) return false;
			if (filter === 'static' && m.static.length === 0) return false;
			if (filter === 'drift' && !m.genre_drift && !m.studio_drift) return false;
			if (!q) return true;
			// Match across romaji + name_eng + name_jap so an admin
			// searching the title they prefer in their settings still
			// hits rows whose canonical title is the other language.
			const haystacks = [
				m.anime_title, m.anime_name_eng, m.anime_name_jap,
				m.media_title, m.media_name_eng, m.media_name_jap,
				String(m.media_mal_id),
			];
			return haystacks.some((h) => h?.toLowerCase().includes(q));
		});
	});

	const FILTER_CHIPS: { key: Filter; label: string; tooltip: string }[] = [
		{ key: 'all', label: 'All', tooltip: 'Show every media row that changed.' },
		{
			key: 'dynamic',
			label: 'Dynamic only',
			tooltip: 'Volatile fields MAL moves frequently: score, scored_by, episodes, airing_status, aired_to.',
		},
		{
			key: 'static',
			label: 'Static only',
			tooltip: 'Metadata fields MAL changes rarely: title, name_eng, name_jap, other_names, description, cover_image, age_rating, original_source.',
		},
		{
			key: 'drift',
			label: 'Has genre/studio drift',
			tooltip: 'Media where the genre or studio M2M set changed.',
		},
	];
</script>

<svelte:head>
	<title>Job {uuid.slice(0, 8)} — Phsar</title>
</svelte:head>

<div class="mx-auto max-w-5xl space-y-6 p-4">
	{#if loading && !job}
		<p class="text-muted-foreground text-sm">Loading job…</p>
	{:else if error}
		<Notice>
			<p>{error}</p>
		</Notice>
	{:else if job}
		<JobDetailHeader {job} />

		{#if job.kind === 'update_sweep'}
			{#if v2Summary?.counters}
				<JobDetailCounters
					counters={v2Summary.counters}
					merge_detect_failed={v2Summary.merge_detect_failed}
					cache_recompute_failed={v2Summary.cache_recompute_failed}
				/>
			{:else}
				<Notice>
					<p>This sweep predates v0.14.5's per-media diff capture (job version {job.version}). Per-media diffs and the granular counters are not available; the row's payload summary on the Jobs Log is the full record.</p>
				</Notice>
			{/if}

			{#if v2Summary && (v2Summary.media_changes?.length ?? 0) > 0}
				<Card.Root>
					<Card.Header class="space-y-2">
						<div class="flex items-center justify-between gap-3 flex-wrap">
							<h2 class="text-lg font-semibold text-card-foreground">Media changes</h2>
							<span class="text-xs text-muted-foreground">
								Showing {visibleMediaChanges.length} of {v2Summary.media_changes?.length ?? 0}
							</span>
						</div>
						<div class="flex flex-col gap-2 sm:flex-row sm:items-center">
							<Input
								bind:value={search}
								placeholder="Substring match on title or mal_id…"
								class="sm:w-72"
							/>
							<div class="flex gap-1 flex-wrap">
								{#each FILTER_CHIPS as chip (chip.key)}
									<button
										type="button"
										title={chip.tooltip}
										class="px-2 py-1 rounded-full text-xs border transition-colors {filter === chip.key ? 'border-primary bg-primary/15 text-primary' : 'border-border text-muted-foreground hover:bg-muted/30'}"
										onclick={() => (filter = chip.key)}
									>
										{chip.label}
									</button>
								{/each}
							</div>
						</div>
					</Card.Header>
					<Card.Content class="space-y-3">
						{#if visibleMediaChanges.length === 0}
							<p class="text-muted-foreground text-sm">No media changes match the current filter.</p>
						{:else}
							{#each visibleMediaChanges as change (change.media_uuid)}
								<MediaChangeCard {change} />
							{/each}
						{/if}
					</Card.Content>
				</Card.Root>
			{/if}

			{#if v2Summary && (v2Summary.anime_umbrella_changes?.length ?? 0) > 0}
				<Card.Root>
					<Card.Header>
						<h2 class="text-lg font-semibold text-card-foreground">Anime umbrella changes</h2>
					</Card.Header>
					<Card.Content class="space-y-3">
						{#each v2Summary.anime_umbrella_changes ?? [] as change (change.anime_uuid)}
							<AnimeUmbrellaCard {change} />
						{/each}
					</Card.Content>
				</Card.Root>
			{/if}
		{:else}
			<!-- Non-update_sweep detail view: header is the full story for now;
				 the Jobs Log entry shouldn't have been clickable anyway. -->
			<Notice>
				<p>This job kind doesn't carry a per-media diff. The Jobs Log row already shows everything captured for {job.kind}.</p>
			</Notice>
		{/if}
	{/if}
</div>
