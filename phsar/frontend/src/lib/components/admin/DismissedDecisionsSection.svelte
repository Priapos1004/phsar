<script lang="ts" generics="T extends { uuid: string; dismissed_at: string | null }">
	import { api, ApiError } from '$lib/api';
	import { Button } from '$lib/components/ui/button';
	import { Input } from '$lib/components/ui/input';
	import * as Dialog from '$lib/components/ui/dialog';
	import Tooltip from '$lib/components/Tooltip.svelte';
	import { ChevronRight, ChevronDown, RotateCcw } from 'lucide-svelte';
	import { bumpCurationRefresh, curationRefresh, onBump } from '$lib/stores/jobs';
	import { formatShortDateTime } from '$lib/utils/formatString';
	import type { Snippet } from 'svelte';

	interface Props {
		/** Decision kind, woven into copy (e.g. "merge" / "split"). */
		kind: string;
		/** GET endpoint returning the dismissed list. */
		listUrl: string;
		/** Base path; delete POSTs to `${basePath}/${uuid}/delete`. */
		basePath: string;
		/** Admin username for the confirm gate (empty disables the delete button). */
		currentUsername: string;
		/** Per-row renderer the parent card supplies. */
		row: Snippet<[T]>;
		/**
		 * Called after a successful delete so the parent can re-run detection
		 * (its Re-detect handler) — the deleted decision only resurfaces once
		 * the detector re-flags it, and this refreshes the pending list too.
		 */
		onResurfaced?: () => void | Promise<void>;
	}
	let { kind, listUrl, basePath, currentUsername, row, onResurfaced }: Props = $props();

	// Keep the dismissed list (and its counter) fresh: any curation action —
	// a dismiss in the parent card, a delete here, or a re-detect that flagged
	// rows — bumps `curationRefresh`, so re-fetch if we've already loaded.
	$effect(() => onBump(curationRefresh, () => { if (loaded) void load(); }));

	// Lazy: the list is only fetched the first time the section is expanded so
	// the (common) pending view never pays for the dismissed history.
	let expanded = $state(false);
	let loaded = $state(false);
	let loading = $state(false);
	let items = $state<T[]>([]);
	let error = $state('');

	let deleteUuid = $state<string | null>(null);
	let confirmInput = $state('');
	let deleting = $state(false);
	let deleteError = $state('');

	async function toggle() {
		expanded = !expanded;
		if (expanded && !loaded) await load();
	}

	async function load() {
		loading = true;
		error = '';
		try {
			items = await api.get<T[]>(listUrl);
			loaded = true;
		} catch (err) {
			error = err instanceof ApiError ? err.detail : 'Failed to load dismissed decisions';
		} finally {
			loading = false;
		}
	}

	function openDelete(uuid: string) {
		deleteUuid = uuid;
		confirmInput = '';
		deleteError = '';
	}

	async function handleDelete() {
		if (!deleteUuid || confirmInput !== currentUsername) return;
		deleting = true;
		deleteError = '';
		try {
			await api.post(`${basePath}/${deleteUuid}/delete`, { confirm: confirmInput });
			items = items.filter((it) => it.uuid !== deleteUuid);
			deleteUuid = null;
			bumpCurationRefresh();
			// Resurface now: re-run detection so the freed candidate re-flags
			// as pending and the parent's pending list refreshes immediately,
			// rather than waiting for the nightly sweep.
			await onResurfaced?.();
		} catch (err) {
			deleteError = err instanceof ApiError ? err.detail : 'Failed to delete decision';
		} finally {
			deleting = false;
		}
	}
</script>

<div class="border-t border-border/60 pt-3 mt-3">
	<button
		type="button"
		class="text-xs text-muted-foreground hover:text-primary transition flex items-center gap-1"
		onclick={toggle}
	>
		{#if expanded}<ChevronDown class="size-3" />{:else}<ChevronRight class="size-3" />{/if}
		<span>Dismissed decisions{loaded ? ` (${items.length})` : ''}</span>
	</button>

	{#if expanded}
		{#if loading}
			<p class="text-xs text-muted-foreground mt-2">Loading…</p>
		{:else if error}
			<p class="text-xs text-destructive mt-2">{error}</p>
		{:else if items.length === 0}
			<p class="text-xs text-muted-foreground mt-2">No dismissed {kind} decisions.</p>
		{:else}
			<div class="space-y-2 mt-2">
				{#each items as item (item.uuid)}
					<div class="rounded border bg-muted/20 px-3 py-2 flex items-start justify-between gap-3">
						<div class="min-w-0 space-y-1">
							{@render row(item)}
							{#if item.dismissed_at}
								<p class="text-[11px] text-muted-foreground">
									Dismissed {formatShortDateTime(item.dismissed_at)}
								</p>
							{/if}
						</div>
						<Tooltip text="Delete this dismissal so the {kind} can resurface on the next detection">
							{#snippet trigger(props)}
								<Button
									{...props}
									variant="ghost"
									size="sm"
									class="shrink-0"
									onclick={() => openDelete(item.uuid)}
								>
									<RotateCcw class="size-4 mr-1" /> Resurface
								</Button>
							{/snippet}
						</Tooltip>
					</div>
				{/each}
			</div>
		{/if}
	{/if}
</div>

<Dialog.Root open={deleteUuid !== null} onOpenChange={(open) => { if (!open) deleteUuid = null; }}>
	<Dialog.Content class="sm:max-w-md">
		<Dialog.Header>
			<Dialog.Title class="text-destructive">Delete dismissed decision</Dialog.Title>
			<Dialog.Description>
				This removes the dismissal so the {kind} candidate can resurface on the next
				detection — run “Re-detect” to resurface it now, or wait for the nightly sweep.
				To confirm, type your admin username (<strong>{currentUsername}</strong>) below.
			</Dialog.Description>
		</Dialog.Header>
		<Input
			bind:value={confirmInput}
			placeholder={currentUsername}
			disabled={!currentUsername || deleting}
			onkeydown={(e: KeyboardEvent) => {
				if (e.key === 'Enter' && confirmInput === currentUsername) handleDelete();
			}}
		/>
		{#if deleteError}
			<p class="text-sm text-destructive">{deleteError}</p>
		{/if}
		<Dialog.Footer>
			<Button variant="secondary" onclick={() => (deleteUuid = null)} disabled={deleting}>
				Cancel
			</Button>
			<Button
				variant="destructive"
				onclick={handleDelete}
				disabled={deleting || !currentUsername || confirmInput !== currentUsername}
			>
				{deleting ? 'Deleting…' : 'Delete decision'}
			</Button>
		</Dialog.Footer>
	</Dialog.Content>
</Dialog.Root>
