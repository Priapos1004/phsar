<script lang="ts">
	import * as Card from '$lib/components/ui/card';
	import * as Dialog from '$lib/components/ui/dialog';
	import { Button } from '$lib/components/ui/button';
	import { Input } from '$lib/components/ui/input';
	import { Label } from '$lib/components/ui/label';
	import { Badge } from '$lib/components/ui/badge';
	import { Checkbox } from '$lib/components/ui/checkbox';
	import { Pencil, Trash2, X, Check, Plus, Eraser } from 'lucide-svelte';
	import TagColorPicker from './TagColorPicker.svelte';
	import { api, ApiError } from '$lib/api';
	import { tags, refreshTags } from '$lib/stores/tags';
	import { refreshWatchlist } from '$lib/stores/watchlist';
	import { pushToast } from '$lib/stores/toast';
	import { defaultNewTagColor } from '$lib/utils/watchlist';
	import * as cls from '$lib/styles/classes';
	import type { Tag } from '$lib/types/api';

	interface Props {
		/** Called after an edit/delete/empty so the parent reloads the entry list
		 *  (a rename/recolor changes the cards; delete/empty changes membership). */
		onEntriesChanged?: () => void;
	}

	let { onEntriesChanged }: Props = $props();

	// Create
	let newName = $state('');
	let newColor = $state(defaultNewTagColor());
	let creating = $state(false);
	let createError = $state('');

	// Edit (inline)
	let editingUuid = $state<string | null>(null);
	let editName = $state('');
	let editColor = $state('');
	let savingEdit = $state(false);
	let editError = $state('');

	// Delete / empty dialogs
	let deleteTarget = $state<Tag | null>(null);
	let deleteReassign = $state(false);
	let deleting = $state(false);
	let emptyTarget = $state<Tag | null>(null);
	let emptying = $state(false);
	let dialogError = $state('');

	function countLabel(t: Tag): string {
		if (t.entry_count === 0) return 'empty';
		return `${t.anime_count} anime · ${t.entry_count} media`;
	}

	const errText = (err: unknown, fallback: string) => (err instanceof ApiError ? err.detail : fallback);

	async function afterMutation() {
		// Refresh the bookmark store; the parent's reload (onEntriesChanged → load) owns
		// the tag-list + entry refresh, so don't refetch tags here too. Fall back to a tag
		// refresh only if used without a parent callback.
		await refreshWatchlist();
		if (onEntriesChanged) onEntriesChanged();
		else await refreshTags();
	}

	async function handleCreate() {
		if (!newName.trim()) return;
		creating = true;
		createError = '';
		try {
			await api.post('/watchlist/tags', { name: newName.trim(), color: newColor });
			await refreshTags();
			pushToast('List created', 'success');
			newName = '';
			newColor = defaultNewTagColor();
		} catch (err) {
			createError = errText(err, 'Failed to create list');
		} finally {
			creating = false;
		}
	}

	function startEdit(t: Tag) {
		editingUuid = t.uuid;
		editName = t.name;
		editColor = t.color;
		editError = '';
	}

	async function handleSaveEdit(t: Tag) {
		// Unchanged → close silently: no request, no toast (the Save button is also disabled when clean).
		if (editName.trim() === t.name && editColor === t.color) {
			editingUuid = null;
			return;
		}
		savingEdit = true;
		editError = '';
		try {
			await api.patch(`/watchlist/tags/${t.uuid}`, { name: editName.trim(), color: editColor });
			await afterMutation();
			pushToast('List updated', 'success');
			editingUuid = null;
		} catch (err) {
			editError = errText(err, 'Failed to update list');
		} finally {
			savingEdit = false;
		}
	}

	async function handleDelete() {
		if (!deleteTarget) return;
		deleting = true;
		dialogError = '';
		try {
			await api.del(`/watchlist/tags/${deleteTarget.uuid}?reassign_entries=${deleteReassign}`);
			await afterMutation();
			pushToast(deleteReassign ? 'List deleted, entries moved to Watchlist' : 'List deleted', 'success');
			deleteTarget = null;
		} catch (err) {
			dialogError = errText(err, 'Failed to delete list');
		} finally {
			deleting = false;
		}
	}

	async function handleEmpty() {
		if (!emptyTarget) return;
		emptying = true;
		dialogError = '';
		try {
			await api.post(`/watchlist/tags/${emptyTarget.uuid}/empty`, {});
			await afterMutation();
			pushToast('List emptied', 'success');
			emptyTarget = null;
		} catch (err) {
			dialogError = errText(err, 'Failed to empty list');
		} finally {
			emptying = false;
		}
	}
</script>

<div class="space-y-4">
	<!-- Create -->
	<Card.Root class={cls.cardGlass}>
		<Card.Content class="py-4 space-y-3">
			<Label class="text-card-foreground font-medium">New list</Label>
			<div class="flex flex-wrap items-end gap-3">
				<div class="flex-grow min-w-[12rem] space-y-1">
					<Input bind:value={newName} maxlength={50} placeholder="List name…" class="bg-card" />
				</div>
				<TagColorPicker bind:value={newColor} />
				<Button onclick={handleCreate} disabled={creating || !newName.trim()}>
					<Plus class="size-4 mr-1.5" />
					{creating ? 'Adding…' : 'Add'}
				</Button>
			</div>
			{#if createError}<p class="text-destructive text-sm">{createError}</p>{/if}
		</Card.Content>
	</Card.Root>

	<!-- List of tags -->
	<Card.Root class={cls.cardGlass}>
		<Card.Content class="p-0 divide-y divide-border">
			{#each $tags as tag (tag.uuid)}
				<div class="p-3">
					{#if editingUuid === tag.uuid}
						{@const dirty = editName.trim() !== tag.name || editColor !== tag.color}
						<!-- Inline edit -->
						<div class="space-y-2">
							<!-- Name + color + save/cancel on one row (color picker inline, not below). -->
							<div class="flex items-center gap-2">
								<Input bind:value={editName} maxlength={50} class="bg-card flex-grow" />
								<TagColorPicker bind:value={editColor} />
								<!-- Save enables + turns green only when something changed; Cancel turns red (it discards a change). -->
								<Button size="sm" variant="secondary" class={dirty ? 'bg-emerald-100 text-emerald-800 hover:bg-emerald-200' : ''} onclick={() => handleSaveEdit(tag)} disabled={savingEdit || !editName.trim() || !dirty}>
									<Check class="size-4" />
								</Button>
								<Button size="sm" variant="ghost" class={dirty ? cls.btnGhostDestructive : ''} onclick={() => (editingUuid = null)} disabled={savingEdit}>
									<X class="size-4" />
								</Button>
							</div>
							{#if editError}<p class="text-destructive text-sm">{editError}</p>{/if}
						</div>
					{:else}
						<div class="flex items-center gap-3">
							<span class="size-4 rounded-full shrink-0 border border-border" style="background:{tag.color}"></span>
							<span class="font-medium text-card-foreground">{tag.name}</span>
							{#if tag.is_default}<Badge variant="secondary" class="text-[10px]">Default</Badge>{/if}
							<span class="text-xs text-muted-foreground">{countLabel(tag)}</span>
							<div class="flex-grow"></div>
							{#if tag.is_default}
								<!-- Default list can't be deleted, only emptied -->
								<Button size="sm" variant="ghost" onclick={() => { dialogError = ''; emptyTarget = tag; }} disabled={tag.entry_count === 0}>
									<Eraser class="size-4 mr-1.5" /> Empty
								</Button>
							{:else}
								<Button size="sm" variant="ghost" onclick={() => startEdit(tag)} aria-label="Edit list">
									<Pencil class="size-4" />
								</Button>
								<Button size="sm" variant="ghost" class={cls.btnGhostDestructive} onclick={() => { dialogError = ''; deleteReassign = false; deleteTarget = tag; }} aria-label="Delete list">
									<Trash2 class="size-4" />
								</Button>
							{/if}
						</div>
					{/if}
				</div>
			{/each}
		</Card.Content>
	</Card.Root>
</div>

<!-- Delete confirm (non-default) -->
<Dialog.Root open={deleteTarget !== null} onOpenChange={(o) => { if (!o) deleteTarget = null; }}>
	<Dialog.Content class="sm:max-w-md">
		<Dialog.Header>
			<Dialog.Title>Delete list “{deleteTarget?.name}”?</Dialog.Title>
			<Dialog.Description>
				{#if deleteTarget && deleteTarget.entry_count > 0}
					It has {deleteTarget.anime_count} anime ({deleteTarget.entry_count} media).
				{:else}
					This list is empty.
				{/if}
			</Dialog.Description>
		</Dialog.Header>
		{#if deleteTarget && deleteTarget.entry_count > 0}
			<label class="flex items-center gap-2 text-sm text-card-foreground cursor-pointer py-1">
				<Checkbox bind:checked={deleteReassign} />
				Move its entries to the default list instead of deleting them
			</label>
		{/if}
		{#if dialogError}<p class="text-destructive text-sm">{dialogError}</p>{/if}
		<Dialog.Footer>
			<Button variant="secondary" onclick={() => (deleteTarget = null)} disabled={deleting}>Cancel</Button>
			<Button variant="destructive" onclick={handleDelete} disabled={deleting}>
				{deleting ? 'Deleting…' : 'Delete'}
			</Button>
		</Dialog.Footer>
	</Dialog.Content>
</Dialog.Root>

<!-- Empty confirm (default) -->
<Dialog.Root open={emptyTarget !== null} onOpenChange={(o) => { if (!o) emptyTarget = null; }}>
	<Dialog.Content class="sm:max-w-md">
		<Dialog.Header>
			<Dialog.Title>Empty “{emptyTarget?.name}”?</Dialog.Title>
			<Dialog.Description>
				{#if emptyTarget}
					This removes all {emptyTarget.anime_count} anime ({emptyTarget.entry_count} media) from the list.
				{/if}
			</Dialog.Description>
		</Dialog.Header>
		{#if dialogError}<p class="text-destructive text-sm">{dialogError}</p>{/if}
		<Dialog.Footer>
			<Button variant="secondary" onclick={() => (emptyTarget = null)} disabled={emptying}>Cancel</Button>
			<Button variant="destructive" onclick={handleEmpty} disabled={emptying}>
				{emptying ? 'Emptying…' : 'Empty'}
			</Button>
		</Dialog.Footer>
	</Dialog.Content>
</Dialog.Root>
