<script lang="ts">
	import * as Dialog from '$lib/components/ui/dialog';
	import { Button } from '$lib/components/ui/button';
	import { Label } from '$lib/components/ui/label';
	import { Slider } from '$lib/components/ui/slider';
	import { Textarea } from '$lib/components/ui/textarea';
	import AttributeSelect from '$lib/components/AttributeSelect.svelte';
	import RatingNeighbors from '$lib/components/RatingNeighbors.svelte';
	import { ChevronDown, ChevronUp } from 'lucide-svelte';
	import { clampAndSnapScore, decimalPlaces } from '$lib/utils/formatString';
	import { RATING_ATTRIBUTE_OPTIONS } from '$lib/types/api';
	import type { RatingOut } from '$lib/types/api';
	import { api, ApiError } from '$lib/api';
	import { userSettings } from '$lib/stores/userSettings';

	interface Props {
		open: boolean;
		// Already filtered to the ratable subset (not-yet-aired media are excluded
		// by the caller — they stay selectable for the watchlist but can't be rated).
		selectedUuids: Set<string>;
		excludedNotYetAiredCount?: number;
		alreadyRatedCount: number;
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

	let snappedScore = $derived(clampAndSnapScore(score, SCORE_STEP));
	let setAttrCount = $derived(Object.keys(RATING_ATTRIBUTE_OPTIONS).filter(k => attributes[k]).length);
	let totalAttrCount = Object.keys(RATING_ATTRIBUTE_OPTIONS).length;

	export function reset() {
		score = 5.0;
		note = '';
		showAttributes = false;
		attributes = Object.fromEntries(Object.keys(RATING_ATTRIBUTE_OPTIONS).map(k => [k, null]));
		error = '';
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

			<!-- Score: editable circle + slider -->
			<div class="flex flex-col items-center py-2 space-y-3">
				<div class="w-24 h-24 rounded-full bg-primary/10 border-2 border-primary/30 flex items-center justify-center">
					<input
						type="text"
						inputmode="decimal"
						value={snappedScore.toFixed(SCORE_DECIMALS)}
						onblur={(e) => {
							const parsed = parseFloat(e.currentTarget.value.replace(',', '.')) || 0;
							score = clampAndSnapScore(parsed, SCORE_STEP);
							e.currentTarget.value = clampAndSnapScore(parsed, SCORE_STEP).toFixed(SCORE_DECIMALS);
						}}
						onkeydown={(e) => { if (e.key === 'Enter') e.currentTarget.blur(); }}
						class="w-20 text-center text-2xl font-bold text-card-foreground bg-transparent outline-none"
					/>
				</div>
				<div class="w-full max-w-xs">
					<Slider type="single" bind:value={score} min={0} max={10} step={SCORE_STEP} />
				</div>
			</div>

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
