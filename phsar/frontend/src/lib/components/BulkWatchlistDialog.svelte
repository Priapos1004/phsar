<script lang="ts">
	// Add or update several media's watchlist entries at once.
	//
	// It runs in two modes over the same form. ADD is the fresh case. UPDATE prefills
	// from the entries it is about to rewrite, which it has to: a bulk write applies one
	// list + priority to every selected media, so a dialog that opened on defaults would
	// downgrade a High entry to the default on its way to another list — and moving an
	// anime between lists is exactly what this dialog is for. When the entries disagree
	// the field stays unset and the user picks, rather than a silent winner.
	import { onDestroy, untrack } from 'svelte';
	import * as Dialog from '$lib/components/ui/dialog';
	import { Button } from '$lib/components/ui/button';
	import { Label } from '$lib/components/ui/label';
	import { Textarea } from '$lib/components/ui/textarea';
	import { Checkbox } from '$lib/components/ui/checkbox';
	import { Bookmark, Trash2 } from 'lucide-svelte';
	import { api, ApiError } from '$lib/api';
	import { tags } from '$lib/stores/tags';
	import { refreshWatchlist, watchlistTags } from '$lib/stores/watchlist';
	import { pushToast } from '$lib/stores/toast';
	import WatchlistTagSelect from '$lib/components/WatchlistTagSelect.svelte';
	import PriorityPicker from '$lib/components/PriorityPicker.svelte';
	import { uniformEntryFields } from '$lib/utils/watchlist';
	import type { WatchlistAnimeEntries, WatchlistOut } from '$lib/types/api';

	interface Props {
		open: boolean;
		title?: string;
		/** Always-included media UUIDs. */
		mediaUuids: string[];
		/** Optional extra media behind a checkbox (e.g. an anime's side stories). */
		optionalMediaUuids?: string[];
		optionalLabel?: string;
		/** Set to prefill from this anime's existing entries (one GET on open). */
		animeUuid?: string;
		/** Provided = render the remove button (the hero's "take the whole anime off"). */
		onRemove?: () => Promise<void>;
		onSaved?: () => void;
	}

	let {
		open = $bindable(),
		title = 'Add to watchlist',
		mediaUuids,
		optionalMediaUuids = [],
		optionalLabel = '',
		animeUuid,
		onRemove,
		onSaved,
	}: Props = $props();

	let priority = $state<number | undefined>(3);
	let note = $state('');
	let tagUuid = $state<string | undefined>(undefined);
	let includeOptional = $state(false);
	let loading = $state(false);
	let saving = $state(false);
	let removing = $state(false);
	let error = $state('');
	/** This anime's existing entries, or [] when none were fetched. */
	let entries = $state<WatchlistOut[]>([]);
	/** Which media the backend will write the note to — its rule, not ours. */
	let noteTargetUuid = $state<string | null>(null);

	let defaultTagUuid = $derived($tags.find((t) => t.is_default)?.uuid);
	let hasOptional = $derived(optionalMediaUuids.length > 0);
	let effectiveUuids = $derived(
		includeOptional ? [...mediaUuids, ...optionalMediaUuids] : mediaUuids
	);

	// Only the entries this save would actually rewrite decide the prefill — the anime
	// may have watchlisted media outside the current selection.
	let scopedEntries = $derived(entries.filter((e) => effectiveUuids.includes(e.media_uuid)));
	let isUpdate = $derived(scopedEntries.length > 0);
	let uniform = $derived(uniformEntryFields(scopedEntries));
	let mixed = $derived(isUpdate && (uniform.tagCount > 1 || uniform.priorityCount > 1));
	/** "2 lists", "2 priorities", or both — what the entries disagree on. */
	let spans = $derived(
		[
			uniform.tagCount > 1 ? `${uniform.tagCount} lists` : null,
			uniform.priorityCount > 1 ? `${uniform.priorityCount} priorities` : null,
		]
			.filter(Boolean)
			.join(' and ')
	);
	// Notes on entries the save cannot touch — they survive it, which is worth saying
	// since the box only shows the one note this dialog can change.
	let untouchedNotes = $derived(
		scopedEntries.filter((e) => e.note && e.media_uuid !== noteTargetUuid).length
	);
	// Media in the selection already listed but NOT prefilled from (add mode) — the
	// existing overwrite warning.
	let alreadyOnCount = $derived(effectiveUuids.filter((u) => $watchlistTags.has(u)).length);

	// What the prefill put in the fields, snapshotted at prefill time so the dirty check
	// compares against what the user was actually shown.
	let prefilled = $state<{ tagUuid?: string; priority?: number; note: string }>({ note: '' });
	// Set only by typing in the note box. The request carries `note` if and only if this
	// is true — a string comparison against the prefill would also fire when the prefill
	// silently failed to land, and sending a note the user never edited rewrites whichever
	// entry the backend picks as the target, destroying the note already there.
	let noteTouched = $state(false);

	// A fresh add is always saveable; an update only once something changed, so the
	// button stays disabled on a no-op edit (mirrors WatchlistDialog).
	let isDirty = $derived(
		!isUpdate ||
			priority !== prefilled.priority ||
			tagUuid !== prefilled.tagUuid ||
			(noteTouched && note.trim() !== prefilled.note.trim())
	);
	let canSave = $derived(
		!!tagUuid && priority !== undefined && effectiveUuids.length > 0 && isDirty
	);

	// untrack: load() writes the state it then prefills from, so a tracked read here
	// would make the effect re-enter itself. Only `open` may schedule it.
	$effect(() => {
		if (open) untrack(() => void load());
		else untrack(disarm);
	});

	async function load() {
		error = '';
		includeOptional = false;
		entries = [];
		noteTargetUuid = null;
		if (!animeUuid) {
			applyPrefill([]);
			return;
		}
		loading = true;
		let fetched: WatchlistOut[] = [];
		try {
			const res = await api.get<WatchlistAnimeEntries>(`/watchlist/anime/${animeUuid}`);
			fetched = res.entries;
			entries = fetched;
			noteTargetUuid = res.note_target_media_uuid;
		} catch (err) {
			// A failed prefill must not present stale defaults as if they were the stored
			// values — surface it and let the user retry rather than save a downgrade.
			error = err instanceof ApiError ? err.detail : 'Failed to load existing entries';
		} finally {
			loading = false;
			applyPrefill(fetched);
		}
	}

	/** Seed the fields from the rows just fetched. Takes them as an argument rather than
	 *  reading the derived chain, which is not guaranteed to have recomputed by the time
	 *  this runs after the await. */
	function applyPrefill(fetched: WatchlistOut[]) {
		const scoped = fetched.filter((e) => mediaUuids.includes(e.media_uuid));
		const u = uniformEntryFields(scoped);
		priority = scoped.length ? u.priority : 3;
		tagUuid = scoped.length ? u.tagUuid : defaultTagUuid;
		// The note of the entry the backend will write to, so the box edits what it shows.
		note = scoped.find((e) => e.media_uuid === noteTargetUuid)?.note ?? '';
		prefilled = { tagUuid, priority, note };
		noteTouched = false;
	}

	// Click-to-arm guard on remove (copied from CompletionStatusCard): the first click
	// reddens and relabels, a second within the window confirms.
	const ARM_TIMEOUT_MS = 3000;
	let armed = $state(false);
	let armTimer: ReturnType<typeof setTimeout> | undefined;

	function disarm() {
		clearTimeout(armTimer);
		armed = false;
	}

	function requestRemove() {
		if (armed) {
			disarm();
			void handleRemove();
			return;
		}
		clearTimeout(armTimer);
		armed = true;
		armTimer = setTimeout(() => (armed = false), ARM_TIMEOUT_MS);
	}

	onDestroy(() => clearTimeout(armTimer));

	async function handleRemove() {
		if (!onRemove) return;
		removing = true;
		error = '';
		try {
			await onRemove();
			open = false;
		} catch (err) {
			error = err instanceof ApiError ? err.detail : 'Failed to remove from watchlist';
		} finally {
			removing = false;
		}
	}

	async function handleSave() {
		if (!tagUuid || priority === undefined) {
			error = 'Pick a list and a priority first';
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
				// Omitted unless the user typed: the backend then leaves every note alone,
				// so changing a list or priority can never disturb one.
				...(noteTouched ? { note: note.trim() || null } : {}),
			});
			await refreshWatchlist();
			pushToast(
				isUpdate ? `Updated ${results.length} on your watchlist` : `Added ${results.length} to watchlist`,
				'success'
			);
			onSaved?.();
			open = false;
		} catch (err) {
			error = err instanceof ApiError ? err.detail : 'Failed to save watchlist entries';
		} finally {
			saving = false;
		}
	}
</script>

<Dialog.Root bind:open>
	<Dialog.Content class="sm:max-w-md">
		<!-- min-w-0 required (see .claude/rules/frontend.md "Dialog children that cannot shrink"). -->
		<Dialog.Header class="min-w-0">
			<Dialog.Title>{isUpdate ? 'Update watchlist entry' : title}</Dialog.Title>
			<Dialog.Description class="text-muted-foreground">
				{#if mixed}
					These {scopedEntries.length} media span {spans} — saving applies your choice to all of them.
				{:else if isUpdate}
					List &amp; priority apply to all {effectiveUuids.length} listed media.
				{:else}
					List &amp; priority apply to all {effectiveUuids.length} selected; the note goes on the first season.
				{/if}
			</Dialog.Description>
		</Dialog.Header>

		<div class="space-y-4 py-2 min-w-0">
			{#if !isUpdate && alreadyOnCount > 0}
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

			<!-- Note — attached to the note-target media only (mirrors bulk rating's last-main note) -->
			<div class="space-y-1">
				<Label class="text-card-foreground">
					Note <span class="text-muted-foreground font-normal">({note.length}/1000)</span>
				</Label>
				<Textarea
					bind:value={note}
					oninput={() => (noteTouched = true)}
					maxlength={1000}
					rows={3}
					placeholder="Optional note…"
					class="bg-card"
				/>
				<p class="text-xs text-muted-foreground">
					{#if untouchedNotes > 0}
						Saved on the first main story media. {untouchedNotes}
						other {untouchedNotes > 1 ? 'media keep their own notes' : 'media keeps its own note'}.
					{:else}
						Added to the first main story media only.
					{/if}
				</p>
			</div>

			{#if error}
				<p class="text-destructive text-sm">{error}</p>
			{/if}

			<div class="flex gap-2">
				<Button class="flex-1" onclick={handleSave} disabled={saving || removing || loading || !canSave}>
					<Bookmark class="size-4 mr-1.5" />
					{#if saving}
						Saving…
					{:else if isUpdate}
						Update {effectiveUuids.length}
					{:else}
						Add {effectiveUuids.length} to watchlist
					{/if}
				</Button>
				{#if onRemove && isUpdate}
					<!-- min-w floor: the armed label is shorter than the idle one, so a plain
					     swap would reflow the row (.claude/rules/frontend.md). -->
					<Button
						variant="destructive"
						class="min-w-32"
						onclick={requestRemove}
						disabled={saving || removing}
					>
						<Trash2 class="size-4 mr-1.5" />
						{#if removing}
							Removing…
						{:else if armed}
							Sure?
						{:else}
							Remove {scopedEntries.length}
						{/if}
					</Button>
				{/if}
			</div>
		</div>
	</Dialog.Content>
</Dialog.Root>
