<script lang="ts">
	import * as Dialog from '$lib/components/ui/dialog';
	import { Button } from '$lib/components/ui/button';
	import { Label } from '$lib/components/ui/label';
	import { Textarea } from '$lib/components/ui/textarea';
	import { Bookmark, Trash2 } from 'lucide-svelte';
	import { api, ApiError } from '$lib/api';
	import { tags } from '$lib/stores/tags';
	import { refreshWatchlist } from '$lib/stores/watchlist';
	import { pushToast } from '$lib/stores/toast';
	import WatchlistTagSelect from '$lib/components/WatchlistTagSelect.svelte';
	import PriorityPicker from '$lib/components/PriorityPicker.svelte';
	import type { WatchlistOut } from '$lib/types/api';

	interface Props {
		open: boolean;
		mediaUuid: string;
		mediaTitle?: string;
		/** Fired after a successful add/update/remove so the caller can react (the icon
		 *  state comes from the watchlist store, refreshed here regardless). */
		onChanged?: () => void;
	}

	let { open = $bindable(), mediaUuid, mediaTitle = '', onChanged }: Props = $props();

	let priority = $state(3);
	let note = $state('');
	let tagUuid = $state<string | undefined>(undefined);
	let existing = $state<WatchlistOut | null>(null);
	let loading = $state(false);
	let saving = $state(false);
	let removing = $state(false);
	let error = $state('');

	let defaultTagUuid = $derived($tags.find((t) => t.is_default)?.uuid);

	// A new entry is always saveable; an existing one only when something actually
	// changed, so the "Update" button stays disabled on a no-op edit.
	let isDirty = $derived(
		!existing ||
			priority !== existing.priority ||
			(note.trim() || null) !== (existing.note ?? null) ||
			tagUuid !== existing.tag.uuid
	);

	// Load the current entry (if any) each time the dialog opens, so an edit shows the
	// stored priority/note/tag and a fresh add shows the defaults.
	$effect(() => {
		if (open) loadEntry();
	});

	async function loadEntry() {
		loading = true;
		error = '';
		try {
			const entry = await api.get<WatchlistOut>(`/watchlist/media/${mediaUuid}`);
			existing = entry;
			priority = entry.priority;
			note = entry.note ?? '';
			tagUuid = entry.tag.uuid;
		} catch (err) {
			if (err instanceof ApiError && err.status === 404) {
				existing = null;
				priority = 3;
				note = '';
				tagUuid = defaultTagUuid;
			} else {
				error = err instanceof ApiError ? err.detail : 'Failed to load watchlist entry';
			}
		} finally {
			loading = false;
		}
	}

	async function handleSave() {
		if (!tagUuid) {
			error = 'Pick a list first';
			return;
		}
		saving = true;
		error = '';
		try {
			await api.put<WatchlistOut>(`/watchlist/media/${mediaUuid}`, {
				tag_uuid: tagUuid,
				priority,
				note: note.trim() || null,
			});
			await refreshWatchlist();
			pushToast(existing ? 'Watchlist updated' : 'Added to watchlist', 'success');
			onChanged?.();
			open = false;
		} catch (err) {
			error = err instanceof ApiError ? err.detail : 'Failed to save';
		} finally {
			saving = false;
		}
	}

	async function handleRemove() {
		removing = true;
		error = '';
		try {
			await api.del(`/watchlist/media/${mediaUuid}`);
			await refreshWatchlist();
			pushToast('Removed from watchlist', 'success');
			onChanged?.();
			open = false;
		} catch (err) {
			error = err instanceof ApiError ? err.detail : 'Failed to remove';
		} finally {
			removing = false;
		}
	}
</script>

<Dialog.Root bind:open>
	<Dialog.Content class="sm:max-w-md">
		<!-- min-w-0 so a long nowrap title can't widen the grid track and push every row past the
		     panel edge — see ShareDialog for the full why. -->
		<Dialog.Header class="min-w-0">
			<Dialog.Title>{existing ? 'Edit watchlist entry' : 'Add to watchlist'}</Dialog.Title>
			{#if mediaTitle}
				<Dialog.Description class="text-muted-foreground truncate">{mediaTitle}</Dialog.Description>
			{/if}
		</Dialog.Header>

		<div class="space-y-4 py-2">
			<!-- List (tag) -->
			<div class="space-y-1">
				<Label class="text-card-foreground">List</Label>
				<WatchlistTagSelect bind:value={tagUuid} />
			</div>

			<!-- Priority -->
			<div class="space-y-1">
				<Label class="text-card-foreground">Priority</Label>
				<PriorityPicker bind:value={priority} />
			</div>

			<!-- Note -->
			<div class="space-y-1">
				<Label class="text-card-foreground">
					Note <span class="text-muted-foreground font-normal">({note.length}/1000)</span>
				</Label>
				<Textarea bind:value={note} maxlength={1000} rows={3} placeholder="Optional note…" class="bg-card" />
			</div>

			{#if error}
				<p class="text-destructive text-sm">{error}</p>
			{/if}

			<div class="flex gap-2">
				<Button class="flex-1" onclick={handleSave} disabled={saving || removing || loading || !tagUuid || !isDirty}>
					<Bookmark class="size-4 mr-1.5" />
					{saving ? 'Saving…' : existing ? 'Update' : 'Add'}
				</Button>
				{#if existing}
					<Button variant="destructive" onclick={handleRemove} disabled={saving || removing}>
						<Trash2 class="size-4 mr-1.5" />
						{removing ? 'Removing…' : 'Remove'}
					</Button>
				{/if}
			</div>
		</div>
	</Dialog.Content>
</Dialog.Root>
