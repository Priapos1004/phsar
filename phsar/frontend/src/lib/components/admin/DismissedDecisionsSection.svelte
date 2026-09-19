<script lang="ts" generics="T extends { uuid: string; dismissed_at: string | null }">
	import { api, ApiError } from '$lib/api';
	import { Button } from '$lib/components/ui/button';
	import Tooltip from '$lib/components/Tooltip.svelte';
	import { ChevronRight, ChevronDown, RotateCcw } from 'lucide-svelte';
	import { bumpCurationRefresh, curationRefresh, onBump } from '$lib/stores/jobs';
	import { formatShortDateTime } from '$lib/utils/formatString';
	import { onDestroy } from 'svelte';
	import type { Snippet } from 'svelte';

	interface Props {
		/** Decision kind, woven into copy (e.g. "merge" / "split"). */
		kind: string;
		/** GET endpoint returning the dismissed list. */
		listUrl: string;
		/** Base path; delete POSTs to `${basePath}/${uuid}/delete`. */
		basePath: string;
		/** Per-row renderer the parent card supplies. */
		row: Snippet<[T]>;
		/**
		 * Called after a successful delete so the parent can re-run detection
		 * (its Re-detect handler) — the deleted decision only resurfaces once
		 * the detector re-flags it, and this refreshes the pending list too.
		 */
		onResurfaced?: () => void | Promise<void>;
	}
	let { kind, listUrl, basePath, row, onResurfaced }: Props = $props();

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

	// First rung of the confirm ladder in rules/frontend.md.
	const ARM_TIMEOUT_MS = 3000;
	let armedUuid = $state<string | null>(null);
	let armTimer: ReturnType<typeof setTimeout> | undefined;
	let deletingUuid = $state<string | null>(null);
	let deleteError = $state('');

	let resurfaceHint = $derived(
		`Delete this dismissal so the ${kind} can resurface on the next detection`,
	);

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

	function disarm() {
		clearTimeout(armTimer);
		armedUuid = null;
	}

	function requestDelete(uuid: string) {
		if (armedUuid === uuid) {
			disarm();
			void handleDelete(uuid);
			return;
		}
		clearTimeout(armTimer);
		deleteError = '';
		armedUuid = uuid;
		armTimer = setTimeout(() => (armedUuid = null), ARM_TIMEOUT_MS);
	}

	onDestroy(() => clearTimeout(armTimer));

	async function handleDelete(uuid: string) {
		deletingUuid = uuid;
		deleteError = '';
		try {
			await api.post(`${basePath}/${uuid}/delete`, {});
			items = items.filter((it) => it.uuid !== uuid);
			bumpCurationRefresh();
			// Resurface now: re-run detection so the freed candidate re-flags
			// as pending and the parent's pending list refreshes immediately,
			// rather than waiting for the nightly sweep.
			await onResurfaced?.();
		} catch (err) {
			deleteError = err instanceof ApiError ? err.detail : 'Failed to delete decision';
		} finally {
			deletingUuid = null;
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
			{#if deleteError}
				<p class="text-xs text-destructive mt-2">{deleteError}</p>
			{/if}
			<div class="space-y-2 mt-2">
				{#each items as item (item.uuid)}
					{@const armed = armedUuid === item.uuid}
					<div class="rounded border bg-muted/20 px-3 py-2 flex items-start justify-between gap-3">
						<div class="min-w-0 space-y-1">
							{@render row(item)}
							{#if item.dismissed_at}
								<p class="text-[11px] text-muted-foreground">
									Dismissed {formatShortDateTime(item.dismissed_at)}
								</p>
							{/if}
						</div>
						<Tooltip text={armed ? 'Click again to confirm' : resurfaceHint}>
							{#snippet trigger(props)}
								<Button
									{...props}
									variant="ghost"
									size="sm"
									disabled={deletingUuid !== null}
									class="shrink-0 min-w-[7.5rem] {armed
										? 'text-destructive hover:text-destructive'
										: ''}"
									onclick={() => requestDelete(item.uuid)}
								>
									<RotateCcw class="size-4 mr-1" />
									{armed ? 'Sure?' : 'Resurface'}
								</Button>
							{/snippet}
						</Tooltip>
					</div>
				{/each}
			</div>
		{/if}
	{/if}
</div>

