<script lang="ts">
	import { onMount } from 'svelte';
	import { api, ApiError } from '$lib/api';
	import { Button } from '$lib/components/ui/button';
	import * as Card from '$lib/components/ui/card';
	import * as Dialog from '$lib/components/ui/dialog';
	import { Badge } from '$lib/components/ui/badge';
	import { Input } from '$lib/components/ui/input';
	import { Label } from '$lib/components/ui/label';
	import { Checkbox } from '$lib/components/ui/checkbox';
	import Tooltip from '$lib/components/Tooltip.svelte';
	import DismissedDecisionsSection from '$lib/components/admin/DismissedDecisionsSection.svelte';
	import { Trash2, X, RefreshCw, Search, AlertTriangle } from 'lucide-svelte';
	import { bumpCurationRefresh } from '$lib/stores/jobs';
	import { buildDetailHref } from '$lib/utils/navigation';
	import { formatMediaType, formatShortDate, resolveTitle } from '$lib/utils/formatString';
	import { userSettings } from '$lib/stores/userSettings';
	import type { DeleteBackfillResult, DeleteCandidateListItem } from '$lib/types/api';

	let { currentUsername = '' }: { currentUsername?: string } = $props();

	let nameLanguage = $derived($userSettings?.name_language ?? 'english');

	let candidates = $state<DeleteCandidateListItem[]>([]);
	// `loading` flips off after the first fetch and stays off; subsequent
	// fetches only toggle `refreshing`. That keeps the keyed each-block mounted
	// across refreshes so Svelte diffs the list in place — no full unmount, no
	// scroll jump. Same split as the merge and split cards.
	let loading = $state(true);
	let refreshing = $state(false);
	let redetecting = $state(false);
	let busy = $derived(loading || refreshing || redetecting);
	let error = $state('');
	let info = $state('');
	let busyUuid = $state<string | null>(null);
	let confirmDismissUuid = $state<string | null>(null);

	// Removal is the one action behind the username dialog rather than an
	// inline confirm: it deletes catalogue rows and the user data cascading off
	// them, with no undo short of a backup restore — the same severity as the
	// restore itself, so the same gate.
	let removeUuid = $state<string | null>(null);
	let removeBlacklist = $state(false);
	let confirmInput = $state('');
	let removing = $state(false);
	let removeError = $state('');

	let removeTarget = $derived(candidates.find((c) => c.uuid === removeUuid) ?? null);

	onMount(async () => {
		await fetchCandidates();
		loading = false;
	});

	async function refreshCandidates() {
		// Manual user-initiated refresh — clear the stale re-detect summary so
		// it doesn't outlive the run that produced it.
		info = '';
		await fetchCandidates();
	}

	async function fetchCandidates() {
		refreshing = true;
		error = '';
		try {
			candidates = await api.get<DeleteCandidateListItem[]>('/admin/delete-candidates');
		} catch (err) {
			error = err instanceof ApiError ? err.detail : 'Failed to load delete candidates';
		} finally {
			refreshing = false;
		}
	}

	async function handleRedetect() {
		redetecting = true;
		error = '';
		info = '';
		try {
			const result = await api.post<DeleteBackfillResult>('/admin/delete-candidates/backfill', {});
			info =
				result.inserted === 0
					? 'No new candidates found.'
					: `Flagged ${result.inserted} new candidate${result.inserted === 1 ? '' : 's'}.`;
			await fetchCandidates();
			if (result.inserted > 0) bumpCurationRefresh();
		} catch (err) {
			error = err instanceof ApiError ? err.detail : 'Failed to re-run detection';
		} finally {
			redetecting = false;
		}
	}

	async function handleDismiss(uuid: string) {
		busyUuid = uuid;
		error = '';
		info = '';
		try {
			await api.post(`/admin/delete-candidates/${uuid}/dismiss`, {});
			confirmDismissUuid = null;
			candidates = candidates.filter((c) => c.uuid !== uuid);
			bumpCurationRefresh();
		} catch (err) {
			error = err instanceof ApiError ? err.detail : 'Failed to dismiss';
		} finally {
			busyUuid = null;
		}
	}

	function openRemove(c: DeleteCandidateListItem) {
		removeUuid = c.uuid;
		// Default OFF, because the two mistakes cost very different amounts.
		// Forgetting to tick it means the entry comes back on some later sweep
		// and you delete it again — a minute of work. Ticking it when you
		// shouldn't have means the entry can never return, and there is no UI to
		// undo a blacklist.
		removeBlacklist = false;
		confirmInput = '';
		removeError = '';
	}

	async function handleRemove() {
		if (!removeUuid || confirmInput !== currentUsername) return;
		const uuid = removeUuid;
		removing = true;
		removeError = '';
		try {
			await api.post(`/admin/delete-candidates/${uuid}/remove`, {
				confirm: confirmInput,
				blacklist: removeBlacklist,
			});
			removeUuid = null;
			// Refetch rather than filtering locally: removing the last media of
			// an anime deletes the anime, which can resolve sibling candidates.
			await fetchCandidates();
			bumpCurationRefresh();
		} catch (err) {
			removeError = err instanceof ApiError ? err.detail : 'Failed to remove';
		} finally {
			removing = false;
		}
	}

	/** Why the detector flagged this row, in the admin's terms. */
	function reasonLine(c: DeleteCandidateListItem): string {
		if (c.detected_by === 'sweep_404') {
			return `Gone from MAL — 404 on ${formatShortDate(c.created_at)}`;
		}
		if (c.detected_by === 'low_signal') {
			const votes = c.scored_by ?? 0;
			return `No MAL score · ${votes} vote${votes === 1 ? '' : 's'}`;
		}
		return c.detected_by;
	}

	/** Franchise context — the single most important input to the decision.
	 *  Removing a dead entry from a 78-media franchise is routine; removing the
	 *  only media of an anime deletes the anime with it. */
	function scopeLine(c: DeleteCandidateListItem): string {
		if (c.anime_title === null) return 'Media already removed';
		if (c.anime_media_count <= 1) return 'Standalone — deletes the anime too';
		return `1 of ${c.anime_media_count} in ${c.anime_title}`;
	}

	/** What users lose if this media goes — empty when nothing references it, so
	 *  callers test the string instead of carrying a second predicate. */
	function userDataLine(c: DeleteCandidateListItem): string {
		const parts: string[] = [];
		if (c.rating_count > 0)
			parts.push(`${c.rating_count} rating${c.rating_count === 1 ? '' : 's'}`);
		if (c.watchlist_count > 0)
			parts.push(`${c.watchlist_count} watchlist entr${c.watchlist_count === 1 ? 'y' : 'ies'}`);
		return parts.join(' · ');
	}
</script>

<Card.Root>
	<Card.Header>
		<div class="flex items-center justify-between">
			<h2 class="text-lg font-semibold text-card-foreground">
				Delete Candidates ({candidates.length})
			</h2>
			<div class="flex items-center gap-1">
				<Tooltip text="Re-run low-signal detection across the catalog (useful after restoring a backup)">
					{#snippet trigger(props)}
						<Button
							{...props}
							variant="ghost"
							size="sm"
							onclick={handleRedetect}
							disabled={busy}
							aria-label="Re-run delete detection"
						>
							<Search class="size-4 {redetecting ? 'animate-pulse' : ''}" />
						</Button>
					{/snippet}
				</Tooltip>
				<Tooltip text="Refresh">
					{#snippet trigger(props)}
						<Button
							{...props}
							variant="ghost"
							size="sm"
							onclick={refreshCandidates}
							disabled={busy}
							aria-label="Refresh"
						>
							<RefreshCw class="size-4 {refreshing ? 'animate-spin' : ''}" />
						</Button>
					{/snippet}
				</Tooltip>
			</div>
		</div>
		<p class="text-xs text-muted-foreground">
			Entries MAL deleted upstream, and standalone entries that never gained MAL traction.
			Nothing is removed automatically — a MAL outage would otherwise strip the catalog.
		</p>
		{#if info}
			<p class="text-xs text-primary mt-1">{info}</p>
		{/if}
	</Card.Header>
	<Card.Content>
		{#if error}
			<p class="text-destructive text-sm mb-3">{error}</p>
		{/if}

		{#if loading}
			<p class="text-muted-foreground text-sm">Loading…</p>
		{:else if candidates.length === 0}
			<p class="text-muted-foreground text-sm">No pending delete candidates.</p>
		{:else}
			<div class="space-y-3">
				{#each candidates as c (c.uuid)}
					{@const userData = userDataLine(c)}
					<div class="rounded-lg border bg-muted/30 px-4 py-3 space-y-3">
						<div class="flex items-center gap-2 flex-wrap text-xs">
							<Badge class="bg-primary/10 text-primary">{reasonLine(c)}</Badge>
							{#if c.media_type}
								<span class="text-muted-foreground">{formatMediaType(c.media_type)}</span>
							{/if}
							<span class="text-muted-foreground font-mono">mal_id={c.mal_id}</span>
						</div>

						<div class="rounded border bg-card px-3 py-2 space-y-1 min-w-0">
							{#if c.media_uuid}
								<a
									href={buildDetailHref('media', c.media_uuid, { from: 'curation' })}
									class="text-sm font-medium text-card-foreground hover:text-primary transition block break-words"
								>
									{resolveTitle(c.title, c.name_eng, c.name_jap, nameLanguage)}
								</a>
							{:else}
								<p class="text-sm font-medium text-card-foreground break-words">
									{resolveTitle(c.title, c.name_eng, c.name_jap, nameLanguage)}
								</p>
							{/if}
							<p class="text-xs text-muted-foreground">{scopeLine(c)}</p>
							{#if userData}
								<p class="text-xs font-medium text-amber-400 flex items-center gap-1">
									<AlertTriangle class="size-3 shrink-0" />
									Deleting destroys {userData}
								</p>
							{/if}
						</div>

						<div class="flex justify-end gap-2 pt-1">
							{#if confirmDismissUuid === c.uuid}
								<Button
									variant="secondary"
									size="sm"
									onclick={() => (confirmDismissUuid = null)}
									disabled={busyUuid === c.uuid}>Cancel</Button
								>
								<Button
									size="sm"
									onclick={() => handleDismiss(c.uuid)}
									disabled={busyUuid === c.uuid}
								>
									{busyUuid === c.uuid ? 'Keeping…' : 'Confirm keep'}
								</Button>
							{:else}
								<Tooltip text="Keep it — not a removal candidate">
									{#snippet trigger(props)}
										<Button
											{...props}
											variant="ghost"
											size="sm"
											onclick={() => (confirmDismissUuid = c.uuid)}
										>
											<X class="size-4 mr-1" /> Keep
										</Button>
									{/snippet}
								</Tooltip>
								<Tooltip text="Delete this media from the catalog">
									{#snippet trigger(props)}
										<Button
											{...props}
											variant="destructive"
											size="sm"
											onclick={() => openRemove(c)}
										>
											<Trash2 class="size-4 mr-1" /> Delete
										</Button>
									{/snippet}
								</Tooltip>
							{/if}
						</div>
					</div>
				{/each}
			</div>
		{/if}

		<DismissedDecisionsSection
			kind="delete"
			listUrl="/admin/delete-candidates/dismissed"
			basePath="/admin/delete-candidates"
			{currentUsername}
			onResurfaced={handleRedetect}
		>
			{#snippet row(item: DeleteCandidateListItem)}
				<div class="min-w-0">
					<p class="text-sm font-medium text-card-foreground break-words">
						{resolveTitle(item.title, item.name_eng, item.name_jap, nameLanguage)}
					</p>
					<p class="text-xs text-muted-foreground">
						mal_id={item.mal_id} · {item.detected_by}
					</p>
				</div>
			{/snippet}
		</DismissedDecisionsSection>
	</Card.Content>
</Card.Root>

<Dialog.Root
	open={removeUuid !== null}
	onOpenChange={(open) => {
		if (!open) removeUuid = null;
	}}
>
	<Dialog.Content class="sm:max-w-md">
		<Dialog.Header class="min-w-0">
			<Dialog.Title class="text-destructive">Delete from catalog</Dialog.Title>
			<Dialog.Description>
				{#if removeTarget}
					This permanently deletes
					<strong class="break-words"
						>{resolveTitle(
							removeTarget.title,
							removeTarget.name_eng,
							removeTarget.name_jap,
							nameLanguage,
						)}</strong
					>
					{#if removeTarget.anime_media_count <= 1}
						and its anime row{/if}. There is no undo short of restoring a backup.
				{/if}
			</Dialog.Description>
		</Dialog.Header>

		{#if removeTarget}
			{@const userData = userDataLine(removeTarget)}
			{#if userData}
				<p class="text-sm font-medium text-destructive flex items-start gap-1.5">
					<AlertTriangle class="size-4 shrink-0 mt-0.5" />
					<span>This also deletes {userData}, including watch history.</span>
				</p>
			{/if}
		{/if}

		<div class="flex items-start gap-2">
			<Checkbox id="delete-blacklist" bind:checked={removeBlacklist} disabled={removing} />
			<div class="min-w-0">
				<Label for="delete-blacklist" class="text-sm">Block it from being re-added</Label>
				<p class="text-xs text-muted-foreground">
					Records the MAL id so no sweep, probe or scrape brings it back. Off by default —
					there is no undo for a block, whereas a re-added entry just comes back here.
					Tick it for something that should never return.
				</p>
			</div>
		</div>

		<div class="space-y-1.5 min-w-0">
			<Label for="delete-confirm" class="text-sm">
				Type your admin username (<strong>{currentUsername}</strong>) to confirm.
			</Label>
			<Input
				id="delete-confirm"
				bind:value={confirmInput}
				placeholder={currentUsername}
				disabled={!currentUsername || removing}
				onkeydown={(e) => {
					if (e.key === 'Enter' && confirmInput === currentUsername) handleRemove();
				}}
			/>
		</div>

		{#if removeError}
			<p class="text-destructive text-sm">{removeError}</p>
		{/if}

		<Dialog.Footer>
			<Button variant="secondary" onclick={() => (removeUuid = null)} disabled={removing}>
				Cancel
			</Button>
			<Button
				variant="destructive"
				onclick={handleRemove}
				disabled={removing || !currentUsername || confirmInput !== currentUsername}
			>
				{removing ? 'Deleting…' : removeBlacklist ? 'Delete + block' : 'Delete'}
			</Button>
		</Dialog.Footer>
	</Dialog.Content>
</Dialog.Root>
