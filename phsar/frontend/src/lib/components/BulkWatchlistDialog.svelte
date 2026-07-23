<script lang="ts">
	import * as Dialog from '$lib/components/ui/dialog';
	import { Button } from '$lib/components/ui/button';
	import { Label } from '$lib/components/ui/label';
	import { Textarea } from '$lib/components/ui/textarea';
	import { Checkbox } from '$lib/components/ui/checkbox';
	import { Bookmark } from 'lucide-svelte';
	import { api, ApiError } from '$lib/api';
	import { tags } from '$lib/stores/tags';
	import { refreshWatchlist, watchlistTags } from '$lib/stores/watchlist';
	import { pushToast } from '$lib/stores/toast';
	import WatchlistTagSelect from '$lib/components/WatchlistTagSelect.svelte';
	import PriorityPicker from '$lib/components/PriorityPicker.svelte';
	import type { WatchlistOut } from '$lib/types/api';

	interface Props {
		open: boolean;
		title?: string;
		/** Always-included media UUIDs. */
		mediaUuids: string[];
		/** Optional extra media behind a checkbox (e.g. an anime's side stories). */
		optionalMediaUuids?: string[];
		optionalLabel?: string;
		onSaved?: () => void;
	}

	let {
		open = $bindable(),
		title = 'Add to watchlist',
		mediaUuids,
		optionalMediaUuids = [],
		optionalLabel = '',
		onSaved,
	}: Props = $props();

	let priority = $state(3);
	let note = $state('');
	let tagUuid = $state<string | undefined>(undefined);
	let includeOptional = $state(false);
	let saving = $state(false);
	let error = $state('');

	let defaultTagUuid = $derived($tags.find((t) => t.is_default)?.uuid);
	let hasOptional = $derived(optionalMediaUuids.length > 0);
	let effectiveUuids = $derived(
		includeOptional ? [...mediaUuids, ...optionalMediaUuids] : mediaUuids
	);
	// Media in the selection already on the watchlist — bulk add re-tags/re-prioritizes
	// them, so warn (mirrors bulk rating's overwrite notice).
	let alreadyOnCount = $derived(effectiveUuids.filter((u) => $watchlistTags.has(u)).length);

	// Reset + preselect the default tag each time the dialog opens.
	$effect(() => {
		if (open) {
			priority = 3;
			note = '';
			includeOptional = false;
			tagUuid = defaultTagUuid;
			error = '';
		}
	});

	async function handleSave() {
		if (!tagUuid) {
			error = 'Pick a list first';
			return;
		}
		if (effectiveUuids.length === 0) {
			error = 'Nothing to add';
			return;
		}
		saving = true;
		error = '';
		try {
			const results = await api.put<WatchlistOut[]>('/watchlist/bulk', {
				media_uuids: effectiveUuids,
				tag_uuid: tagUuid,
				priority,
				note: note.trim() || null,
			});
			await refreshWatchlist();
			pushToast(`Added ${results.length} to watchlist`, 'success');
			onSaved?.();
			open = false;
		} catch (err) {
			error = err instanceof ApiError ? err.detail : 'Failed to add to watchlist';
		} finally {
			saving = false;
		}
	}
</script>

<Dialog.Root bind:open>
	<Dialog.Content class="sm:max-w-md">
		<Dialog.Header>
			<Dialog.Title>{title}</Dialog.Title>
			<Dialog.Description class="text-muted-foreground">
				List &amp; priority apply to all {effectiveUuids.length} selected; the note goes on the first season.
			</Dialog.Description>
		</Dialog.Header>

		<div class="space-y-4 py-2">
			{#if alreadyOnCount > 0}
				<div class="rounded-lg border border-yellow-200 bg-yellow-50 px-3 py-2 text-sm text-yellow-800">
					This will overwrite {alreadyOnCount} existing watchlist {alreadyOnCount > 1 ? 'entries' : 'entry'}.
				</div>
			{/if}

			{#if hasOptional}
				<label class="flex items-center gap-2 text-sm text-card-foreground cursor-pointer">
					<Checkbox bind:checked={includeOptional} />
					{optionalLabel} ({optionalMediaUuids.length})
				</label>
			{/if}

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

			<!-- Note — attached to the first main season only (mirrors bulk rating's last-main note) -->
			<div class="space-y-1">
				<Label class="text-card-foreground">
					Note <span class="text-muted-foreground font-normal">({note.length}/1000)</span>
				</Label>
				<Textarea bind:value={note} maxlength={1000} rows={3} placeholder="Optional note…" class="bg-card" />
				<p class="text-xs text-muted-foreground">Added to the first main story media only.</p>
			</div>

			{#if error}
				<p class="text-destructive text-sm">{error}</p>
			{/if}

			<Button class="w-full" onclick={handleSave} disabled={saving || !tagUuid || effectiveUuids.length === 0}>
				<Bookmark class="size-4 mr-1.5" />
				{saving ? 'Adding…' : `Add ${effectiveUuids.length} to watchlist`}
			</Button>
		</div>
	</Dialog.Content>
</Dialog.Root>
