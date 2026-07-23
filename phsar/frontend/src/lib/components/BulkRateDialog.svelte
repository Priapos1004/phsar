<script lang="ts">
	import * as Dialog from '$lib/components/ui/dialog';
	import { Button } from '$lib/components/ui/button';
	import { Label } from '$lib/components/ui/label';
	import { Textarea } from '$lib/components/ui/textarea';
	import AttributeSelect from '$lib/components/AttributeSelect.svelte';
	import RatingNeighbors from '$lib/components/RatingNeighbors.svelte';
	import ScoreDial from '$lib/components/ScoreDial.svelte';
	import { Checkbox } from '$lib/components/ui/checkbox';
	import { ChevronDown, ChevronUp } from 'lucide-svelte';
	import { clampAndSnapScore, decimalPlaces } from '$lib/utils/formatString';
	import { RATING_ATTRIBUTE_OPTIONS } from '$lib/types/api';
	import type { RatingOut } from '$lib/types/api';
	import { api, ApiError } from '$lib/api';
	import { userSettings } from '$lib/stores/userSettings';
	import { refreshWatchlist } from '$lib/stores/watchlist';
	import { pushToast } from '$lib/stores/toast';

	interface Props {
		open: boolean;
		// Already filtered to the ratable subset (not-yet-aired media are excluded
		// by the caller — they stay selectable for the watchlist but can't be rated).
		selectedUuids: Set<string>;
		excludedNotYetAiredCount?: number;
		alreadyRatedCount: number;
		/** How many of the (ratable) selected media are on the watchlist — drives the
		 *  optional "also remove from watchlist" checkbox. */
		watchlistedCount?: number;
		onSaved: (results: RatingOut[], note: string) => void;
		// Anime context for the rating-consistency helper (bulk rating is anime-scoped, so
		// this excludes the current anime + feeds the tiebreak — same as the media page).
		animeUuid?: string;
		genres?: string[];
		studios?: string[];
		ageRatingNumeric?: number | null;
	}

	let {
		open = $bindable(),
		selectedUuids,
		excludedNotYetAiredCount = 0,
		alreadyRatedCount,
		watchlistedCount = 0,
		onSaved,
		animeUuid,
		genres = [],
		studios = [],
		ageRatingNumeric = null,
	}: Props = $props();

	let nothingToRate = $derived(selectedUuids.size === 0);

	let SCORE_STEP = $derived(parseFloat($userSettings?.rating_step ?? '0.5'));
	let SCORE_DECIMALS = $derived(decimalPlaces(SCORE_STEP));

	let score = $state<number>(5.0);
	let note = $state('');
	let showAttributes = $state(false);
	let attributes = $state<Record<string, string | null>>({});
	let saving = $state(false);
	let error = $state('');
	// Auto-checked: rating a media usually means it's no longer "want to watch".
	let alsoRemoveWatchlist = $state(true);

	let snappedScore = $derived(clampAndSnapScore(score, SCORE_STEP));
	let setAttrCount = $derived(Object.keys(RATING_ATTRIBUTE_OPTIONS).filter(k => attributes[k]).length);
	let totalAttrCount = Object.keys(RATING_ATTRIBUTE_OPTIONS).length;

	export function reset() {
		score = 5.0;
		note = '';
		showAttributes = false;
		attributes = Object.fromEntries(Object.keys(RATING_ATTRIBUTE_OPTIONS).map(k => [k, null]));
		error = '';
		alsoRemoveWatchlist = true;
	}

	async function handleSave() {
		saving = true;
		error = '';

		const payload = {
			media_uuids: [...selectedUuids],
			rating: snappedScore,
			note: note.trim() || null,
			...attributes,
		};

		try {
			const results = await api.put<RatingOut[]>('/ratings/bulk', payload);
			// Rating succeeded — optionally take the watchlisted subset off the watchlist.
			// bulk-delete silently skips media not on the list, so the whole selection is safe.
			if (alsoRemoveWatchlist && watchlistedCount > 0) {
				try {
					await api.post('/watchlist/bulk-delete', { media_uuids: [...selectedUuids] });
					await refreshWatchlist();
				} catch (err) {
					pushToast(err instanceof ApiError ? err.detail : 'Rated, but failed to update the watchlist', 'error');
				}
			}
			onSaved(results, note.trim());
		} catch (err) {
			error = err instanceof ApiError ? err.detail : 'Failed to save ratings';
		} finally {
			saving = false;
		}
	}
</script>

<Dialog.Root bind:open>
	<Dialog.Content class="max-h-[85vh] overflow-y-auto sm:max-w-xl">
		<Dialog.Header>
			<Dialog.Title>Rate {selectedUuids.size} Media</Dialog.Title>
			<Dialog.Description class="text-muted-foreground">
				Score and attributes are applied to all selected media.
			</Dialog.Description>
		</Dialog.Header>

		<!-- min-w-0: Dialog.Content is a CSS grid, whose items default to min-width:auto and
		     refuse to shrink below a nowrap child (a long neighbor title) — this lets the
		     inner truncate engage instead of overflowing the dialog. -->
		<div class="space-y-4 py-2 min-w-0">
			{#if alreadyRatedCount > 0}
				<div class="rounded-lg border border-yellow-200 bg-yellow-50 px-3 py-2 text-sm text-yellow-800">
					This will overwrite {alreadyRatedCount} existing rating{alreadyRatedCount > 1 ? 's' : ''}.
				</div>
			{/if}

			{#if excludedNotYetAiredCount > 0}
				<div class="rounded-lg border border-yellow-200 bg-yellow-50 px-3 py-2 text-sm text-yellow-800">
					{#if nothingToRate}
						{excludedNotYetAiredCount === 1 ? 'The selected media' : `All ${excludedNotYetAiredCount} selected media`}
						{excludedNotYetAiredCount === 1 ? "hasn't" : "haven't"} aired yet, so there's nothing to rate.
					{:else}
						{excludedNotYetAiredCount} selected media {excludedNotYetAiredCount === 1 ? "hasn't" : "haven't"}
						aired yet and {excludedNotYetAiredCount === 1 ? 'is' : 'are'} excluded from this rating.
					{/if}
				</div>
			{/if}

			<!-- Score: editable circle + slider (shared ScoreDial). -->
			<ScoreDial bind:score step={SCORE_STEP} decimals={SCORE_DECIMALS} />

			<div class="bg-muted/40 rounded-lg p-4 space-y-4">
				<!-- Note -->
				<div class="space-y-1">
					<Label class="text-card-foreground">Note <span class="text-muted-foreground font-normal">({note.length}/1000)</span></Label>
					<Textarea
						bind:value={note}
						maxlength={1000}
						rows={3}
						placeholder="Your thoughts on this anime..."
						class="bg-card"
					/>
					<p class="text-xs text-muted-foreground">Applied to the latest-aired main media only.</p>
				</div>

				<!-- Attributes -->
				<div>
					<button
						type="button"
						class="flex items-center gap-2 text-primary group"
						onclick={() => (showAttributes = !showAttributes)}
					>
						{#if showAttributes}
							<ChevronUp class="size-4" />
						{:else}
							<ChevronDown class="size-4" />
						{/if}
						<span class="group-hover:underline">Details</span>
						<span class="text-sm font-normal px-1.5 py-0.5 rounded-full {setAttrCount > 0 ? 'bg-primary/15 text-primary' : 'bg-muted text-muted-foreground'}">
							{setAttrCount}/{totalAttrCount}
						</span>
					</button>

					{#if showAttributes}
						<div class="grid grid-cols-2 gap-3 mt-3">
							{#each Object.entries(RATING_ATTRIBUTE_OPTIONS) as [key, config]}
								<AttributeSelect
									label={config.label}
									options={config.options}
									value={attributes[key] ?? null}
									onChange={(v) => (attributes[key] = v)}
								/>
							{/each}
						</div>
					{/if}
				</div>
			</div>

			<!-- Rating-consistency helper: how you rated nearby-scored titles from other
			     anime (bulk rating is anime-scoped, so this behaves like the media page). -->
			<RatingNeighbors score={snappedScore} {animeUuid} {genres} {studios} {ageRatingNumeric} currentAttributes={attributes} />

			{#if watchlistedCount > 0}
				<!-- Yellow attention block (matches the overwrite warning above): removing from the
				     watchlist is a side effect worth noticing, so it's not a plain checkbox. -->
				<div class="rounded-lg border border-yellow-200 bg-yellow-50 px-3 py-2 space-y-1">
					<label class="flex items-center gap-2 text-sm font-medium text-yellow-800 cursor-pointer">
						<Checkbox bind:checked={alsoRemoveWatchlist} />
						Also remove {watchlistedCount} media from your watchlist
					</label>
					<p class="text-xs text-neutral-600 pl-6">Rating a title usually means it's no longer something you're planning to watch.</p>
				</div>
			{/if}

			{#if error}
				<p class="text-destructive">{error}</p>
			{/if}

			<Button class="w-full" onclick={handleSave} disabled={saving || nothingToRate}>
				{#if saving}
					Saving...
				{:else}
					Rate {selectedUuids.size} Media
				{/if}
			</Button>
		</div>
	</Dialog.Content>
</Dialog.Root>
