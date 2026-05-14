<script lang="ts">
	import { onMount, getContext } from 'svelte';
	import { Plus } from 'lucide-svelte';
	import { api, ApiError } from '$lib/api';
	import { Input } from '$lib/components/ui/input';
	import { Button } from '$lib/components/ui/button';
	import * as Card from '$lib/components/ui/card';
	import Toast from '$lib/components/Toast.svelte';
	import { bumpJobsRefresh, librarySaved, onBump } from '$lib/stores/jobs';
	import { userSettings } from '$lib/stores/userSettings';
	import { formatShortDate, resolveTitle } from '$lib/utils/formatString';
	import { buildDetailHref } from '$lib/utils/navigation';
	import type { Job } from '$lib/types/api';

	const MIN_QUERY_LENGTH = 4;

	const getUserRole = getContext<() => string | null>('userRole');
	let isRestricted = $derived(getUserRole?.() === 'restricted_user');
	let nameLanguage = $derived($userSettings?.name_language ?? 'english');

	interface AnimeRecentItem {
		uuid: string;
		title: string;
		name_eng: string | null;
		name_jap: string | null;
		cover_image: string | null;
		created_at: string;
	}

	const RECENT_LIMIT = 10;

	let query = $state('');
	let submitting = $state(false);
	let errorMsg = $state<string | null>(null);
	let toastShown = $state(false);
	let toastMsg = $state('');
	let recent = $state<AnimeRecentItem[]>([]);
	let recentLoading = $state(true);

	function showToast(msg: string) {
		toastMsg = msg;
		toastShown = true;
		setTimeout(() => (toastShown = false), 2500);
	}

	async function loadRecent() {
		try {
			recent = await api.get<AnimeRecentItem[]>(`/library/recent?limit=${RECENT_LIMIT}`);
		} catch (err) {
			console.error('Failed to load recent additions:', err);
		} finally {
			recentLoading = false;
		}
	}

	onMount(loadRecent);

	// Refresh whenever the bell announces a newly-succeeded user_scrape via
	// the librarySaved store. onBump skips the initial synchronous fire so
	// this doesn't double-fetch with onMount's loadRecent.
	$effect(() => onBump(librarySaved, () => void loadRecent()));

	async function submit(e: SubmitEvent) {
		e.preventDefault();
		const trimmed = query.trim();
		if (trimmed.length < MIN_QUERY_LENGTH) return;
		submitting = true;
		errorMsg = null;
		try {
			await api.post<Job>('/jobs/scrape', { query: trimmed });
			showToast(`Added "${trimmed}" to the queue. Track progress in the bell.`);
			query = '';
			// Tell the bell to refetch immediately so the new job shows up
			// without waiting for its 30s idle poll. The bell will bump
			// librarySaved once the job completes — that's what refreshes
			// the recent-additions panel below, no fixed-delay timer needed.
			bumpJobsRefresh();
		} catch (err) {
			if (err instanceof ApiError) {
				errorMsg = err.detail;
			} else {
				errorMsg = 'Something went wrong. Try again.';
			}
		} finally {
			submitting = false;
		}
	}
</script>

<svelte:head>
	<title>Add to Library — Phsar</title>
</svelte:head>

<Toast message={toastMsg} show={toastShown} />

<div class="max-w-3xl mx-auto py-12">
	<Card.Root>
		<Card.Header>
			<Card.Title>Add to Library</Card.Title>
			<Card.Description>
				Enter an anime title — Phsar searches MyAnimeList, walks the franchise's
				related media, and saves everything connected. Connected entries dedupe
				automatically; unrelated matches each become their own anime.
			</Card.Description>
		</Card.Header>
		<Card.Content>
			<form onsubmit={submit} class="flex flex-col gap-3">
				<Input
					type="text"
					placeholder="e.g. Naruto, Attack on Titan, Steins;Gate"
					bind:value={query}
					disabled={submitting || isRestricted}
					minlength={MIN_QUERY_LENGTH}
					maxlength={200}
					autofocus={!isRestricted}
				/>
				{#if errorMsg}
					<p class="text-sm text-destructive" role="alert">{errorMsg}</p>
				{/if}
				<Button
					type="submit"
					disabled={submitting || isRestricted || query.trim().length < MIN_QUERY_LENGTH}
					class="self-start"
				>
					<Plus class="w-4 h-4 mr-1" />
					{submitting ? 'Queueing…' : 'Add to library'}
				</Button>
				{#if isRestricted}
					<p class="text-xs text-muted-foreground">
						Guest accounts can browse the library but can't add new entries.
					</p>
				{:else}
					<p class="text-xs text-muted-foreground">
						At least {MIN_QUERY_LENGTH} characters — shorter queries are ambiguous on MAL.
					</p>
				{/if}
			</form>
			<p class="mt-4 text-xs text-muted-foreground">
				The job runs in the background. The bell in the top-right shows progress
				and lets you retry on failure.
			</p>
		</Card.Content>
	</Card.Root>

	<div class="mt-10">
		<h2 class="text-lg font-semibold mb-4">Recent additions</h2>
		{#if recentLoading}
			<p class="text-sm text-muted-foreground">Loading…</p>
		{:else if recent.length === 0}
			<p class="text-sm text-muted-foreground">
				Nothing here yet. Add something above to get started.
			</p>
		{:else}
			<div class="grid grid-cols-2 sm:grid-cols-3 md:grid-cols-5 gap-4">
				{#each recent as anime (anime.uuid)}
					{@const displayTitle = resolveTitle(
						anime.title,
						anime.name_eng,
						anime.name_jap,
						nameLanguage,
					)}
					<a
						href={buildDetailHref('anime', anime.uuid, null)}
						class="group flex flex-col gap-2 hover:opacity-90 transition"
					>
						<div class="aspect-[2/3] bg-muted rounded overflow-hidden">
							{#if anime.cover_image}
								<img
									src={anime.cover_image}
									alt={displayTitle}
									class="w-full h-full object-cover group-hover:scale-105 transition"
									loading="lazy"
								/>
							{:else}
								<div
									class="w-full h-full flex items-center justify-center text-xs text-muted-foreground"
								>
									No cover
								</div>
							{/if}
						</div>
						<div class="text-xs">
							<div class="font-medium line-clamp-2">{displayTitle}</div>
							<div class="text-muted-foreground mt-0.5">{formatShortDate(anime.created_at)}</div>
						</div>
					</a>
				{/each}
			</div>
		{/if}
	</div>
</div>
