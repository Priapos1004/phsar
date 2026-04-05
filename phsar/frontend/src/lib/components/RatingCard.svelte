<script lang="ts">
	import * as Card from '$lib/components/ui/card';
	import * as Select from '$lib/components/ui/select';
	import { Button } from '$lib/components/ui/button';
	import { Checkbox } from '$lib/components/ui/checkbox';
	import { Input } from '$lib/components/ui/input';
	import { Label } from '$lib/components/ui/label';
	import { Slider } from '$lib/components/ui/slider';
	import { Textarea } from '$lib/components/ui/textarea';
	import { Badge } from '$lib/components/ui/badge';
	import { api, ApiError } from '$lib/api';
	import { RATING_ATTRIBUTE_OPTIONS } from '$lib/types/api';
	import type { RatingOut, RatingCreate } from '$lib/types/api';
	import { formatDecimalDigits, clampAndSnapScore } from '$lib/utils/formatString';
	import * as cls from '$lib/styles/classes';
	import { ChevronDown, ChevronUp, Star, Pencil, Trash2 } from 'lucide-svelte';

	interface Props {
		mediaUuid: string;
		totalEpisodes: number | null;
		existingRating: RatingOut | null;
		onSaved: (rating: RatingOut) => void;
		onDeleted: () => void;
	}

	let {
		mediaUuid,
		totalEpisodes,
		existingRating,
		onSaved,
		onDeleted,
	}: Props = $props();

	/** Safely index into a typed object by dynamic attribute key. */
	function getAttr(obj: RatingOut | RatingCreate, key: string): string | null {
		return (obj as unknown as Record<string, string | null>)[key] ?? null;
	}

	let editing = $state(false);
	let score = $state<number>(5.0);
	let dropped = $state(false);
	let episodesWatched = $state<string>('');
	let note = $state('');
	let showAttributes = $state(false);
	let saving = $state(false);
	let deleting = $state(false);
	let confirmingDelete = $state(false);
	let error = $state('');
	let attributes = $state<Record<string, string | null>>({});

	let hasChanges = $derived.by(() => {
		if (!existingRating) return true;
		if (score !== existingRating.rating) return true;
		if (dropped !== existingRating.dropped) return true;
		const epVal = episodesWatched ? parseInt(episodesWatched) : null;
		if (epVal !== existingRating.episodes_watched) return true;
		if ((note.trim() || null) !== (existingRating.note ?? null)) return true;
		for (const key of Object.keys(RATING_ATTRIBUTE_OPTIONS)) {
			if ((attributes[key] || null) !== (getAttr(existingRating!, key))) return true;
		}
		return false;
	});

	let filledAttributes = $derived(
		existingRating ? Object.entries(RATING_ATTRIBUTE_OPTIONS)
			.filter(([key]) => getAttr(existingRating!, key))
			.map(([key, config]) => ({
				label: config.label,
				value: config.options.find(o => o.value === getAttr(existingRating!, key))?.label
					?? String(getAttr(existingRating!, key)),
			}))
		: []
	);

	// Step size for score — hardcoded to 0.5 until user settings in v0.12.0
	const SCORE_STEP = 0.5;
	const SCORE_DECIMALS = SCORE_STEP < 1 ? 1 : 0;

	function clampAndSnap(val: number): number {
		return clampAndSnapScore(val, SCORE_STEP);
	}

	let snappedScore = $derived(clampAndSnap(score));
	let setAttrCount = $derived(Object.keys(RATING_ATTRIBUTE_OPTIONS).filter(k => attributes[k]).length);
	let totalAttrCount = Object.keys(RATING_ATTRIBUTE_OPTIONS).length;

	function resetForm() {
		if (existingRating) {
			score = existingRating.rating;
			dropped = existingRating.dropped;
			episodesWatched = existingRating.episodes_watched?.toString() ?? '';
			note = existingRating.note ?? '';
			for (const key of Object.keys(RATING_ATTRIBUTE_OPTIONS)) {
				attributes[key] = getAttr(existingRating!, key);
			}
		} else {
			score = 5.0;
			dropped = false;
			episodesWatched = totalEpisodes?.toString() ?? '';
			note = '';
			for (const key of Object.keys(RATING_ATTRIBUTE_OPTIONS)) {
				attributes[key] = null;
			}
		}
		error = '';
	}

	$effect(() => {
		existingRating;
		resetForm();
		editing = false;
	});

	$effect(() => {
		if (!dropped && totalEpisodes !== null) {
			episodesWatched = totalEpisodes.toString();
		}
	});

	function startEditing() {
		resetForm();
		showAttributes = false;
		editing = true;
	}

	function cancelEditing() {
		resetForm();
		editing = false;
	}

	async function handleSave() {
		saving = true;
		error = '';

		const attrFields: Record<string, string | null> = {};
		for (const key of Object.keys(RATING_ATTRIBUTE_OPTIONS)) {
			attrFields[key] = attributes[key] || null;
		}

		const payload: RatingCreate = {
			rating: snappedScore,
			dropped,
			episodes_watched: episodesWatched ? parseInt(episodesWatched) : null,
			note: note.trim() || null,
			...attrFields,
		};

		try {
			const result = await api.put<RatingOut>(`/ratings/media/${mediaUuid}`, payload);
			onSaved(result);
			editing = false;
		} catch (err) {
			error = err instanceof ApiError ? err.detail : 'Failed to save rating';
		} finally {
			saving = false;
		}
	}

	function requestDelete() {
		confirmingDelete = true;
	}

	function cancelDelete() {
		confirmingDelete = false;
	}

	async function handleDelete() {
		if (!existingRating) return;
		deleting = true;
		error = '';

		try {
			await api.del(`/ratings/${existingRating.uuid}`);
			onDeleted();
			editing = false;
		} catch (err) {
			error = err instanceof ApiError ? err.detail : 'Failed to delete rating';
		} finally {
			deleting = false;
			confirmingDelete = false;
		}
	}
</script>

<Card.Root class={cls.cardGlass}>
	<Card.Content>
		{#if !existingRating && !editing}
			<div class="flex flex-col items-center py-4 space-y-3">
				<div class="w-14 h-14 rounded-full bg-primary/10 flex items-center justify-center">
					<Star class="size-7 text-primary" />
				</div>
				<div class="text-center">
					<h2 class="text-lg font-semibold text-card-foreground">Rate this anime</h2>
					<p class="text-muted-foreground">Share your thoughts</p>
				</div>
				<Button onclick={startEditing}>
					Rate This
				</Button>
			</div>

		{:else if existingRating && !editing}
			<div class="space-y-4">
				<div class="flex items-center justify-between">
					<h2 class="text-sm font-medium text-muted-foreground uppercase tracking-wide">Your Rating</h2>
					<div class="flex gap-1.5">
						<Button variant="secondary" size="sm" onclick={startEditing}>
							<Pencil class="size-3.5 mr-1" /> Edit
						</Button>
						{#if confirmingDelete}
							<Button variant="secondary" size="sm" onclick={cancelDelete} disabled={deleting}>
								Cancel
							</Button>
							<Button variant="destructive" size="sm" onclick={handleDelete} disabled={deleting}>
								{deleting ? '...' : 'Confirm'}
							</Button>
						{:else}
							<Button variant="destructive" size="sm" onclick={requestDelete}>
								<Trash2 class="size-3.5 mr-1" /> Delete
							</Button>
						{/if}
					</div>
				</div>

				<div class="flex items-center gap-4">
					<div class="w-16 h-16 rounded-full bg-primary/10 border-2 border-primary/30 flex items-center justify-center shrink-0">
						<span class="text-xl font-bold text-card-foreground">
							{formatDecimalDigits(existingRating.rating, SCORE_DECIMALS)}
						</span>
					</div>
					<div class="space-y-1">
						<div class="flex items-center gap-2">
							{#if existingRating.dropped}
								<Badge variant="destructive">Dropped</Badge>
							{:else}
								<span class="text-card-foreground font-medium">Completed</span>
							{/if}
							{#if existingRating.episodes_watched !== null}
								<span class="text-muted-foreground">
									· {existingRating.episodes_watched}{totalEpisodes ? `/${totalEpisodes}` : ''} eps
								</span>
							{/if}
						</div>
						{#if filledAttributes.length}
							<div class="flex flex-wrap gap-1">
								{#each filledAttributes as attr}
									<Badge variant="secondary" class="font-normal">
										{attr.label}: {attr.value}
									</Badge>
								{/each}
							</div>
						{/if}
					</div>
				</div>

				{#if existingRating.note}
					<div class="bg-muted/50 rounded-lg px-4 py-3">
						<p class="text-card-foreground/80 italic leading-relaxed">
							"{existingRating.note}"
						</p>
					</div>
				{/if}
			</div>

		{:else}
			<div class="space-y-4">
				<div class="flex items-center justify-between">
					<h2 class="text-sm font-medium text-muted-foreground uppercase tracking-wide">
						{existingRating ? 'Edit Rating' : 'New Rating'}
					</h2>
					<Button variant="secondary" size="sm" onclick={cancelEditing}>
						Cancel
					</Button>
				</div>

				<!-- Score: editable circle + slider -->
				<div class="flex flex-col items-center py-2 space-y-3">
					<div class="w-20 h-20 rounded-full bg-primary/10 border-2 border-primary/30 flex items-center justify-center">
						<input
							type="text"
							inputmode="decimal"
							value={snappedScore.toFixed(SCORE_DECIMALS)}
							onblur={(e) => {
								const parsed = parseFloat(e.currentTarget.value.replace(',', '.')) || 0;
								score = clampAndSnap(parsed);
								e.currentTarget.value = clampAndSnap(parsed).toFixed(SCORE_DECIMALS);
							}}
							onkeydown={(e) => { if (e.key === 'Enter') e.currentTarget.blur(); }}
							class="w-14 text-center text-2xl font-bold text-card-foreground bg-transparent outline-none"
						/>
					</div>
					<div class="w-full max-w-xs">
						<Slider type="single" bind:value={score} min={0} max={10} step={SCORE_STEP} />
					</div>
				</div>

				<div class="bg-muted/40 rounded-lg p-4 space-y-4">
					<!-- Dropped + Episodes on one line -->
					<div class="flex items-center gap-4 flex-wrap">
						<div class="flex items-center gap-2">
							<Checkbox
								checked={dropped}
								onCheckedChange={(val: boolean | 'indeterminate') => { dropped = val === true; }}
							/>
							<Label>Dropped</Label>
						</div>
						<span class="text-border hidden sm:inline">·</span>
						<div class="flex items-center gap-2">
							<Label>Episodes</Label>
							<Input
								type="number"
								min={0}
								max={totalEpisodes ?? undefined}
								bind:value={episodesWatched}
								placeholder="—"
								disabled={!dropped && totalEpisodes !== null}
								class="bg-card w-20 text-center"
							/>
							{#if totalEpisodes !== null}
								<span class="text-muted-foreground">/ {totalEpisodes}</span>
							{/if}
						</div>
					</div>

					<div class="space-y-1">
						<Label>Note <span class="text-muted-foreground font-normal">({note.length}/1000)</span></Label>
						<Textarea
							bind:value={note}
							maxlength={1000}
							rows={3}
							placeholder="Your thoughts on this anime..."
							class="bg-card"
						/>
					</div>

					<!-- Attributes with set/unset indicator -->
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
									<div class="space-y-1">
										<Label class="{attributes[key] ? 'text-card-foreground font-medium' : 'text-muted-foreground'}">
											{config.label}
										</Label>
										<Select.Root
											type="single"
											value={attributes[key] ?? undefined}
											onValueChange={(val: string) => { attributes[key] = val || null; }}
										>
											<Select.Trigger class="w-full {attributes[key] ? 'bg-primary/5 border-2 border-primary/40' : 'bg-card'}">
												{#if attributes[key]}
													{config.options.find(o => o.value === attributes[key])?.label ?? 'Select...'}
												{:else}
													<span class="text-muted-foreground">Not set</span>
												{/if}
											</Select.Trigger>
											<Select.Content>
												{#each config.options as option}
													<Select.Item value={option.value}>{option.label}</Select.Item>
												{/each}
											</Select.Content>
										</Select.Root>
									</div>
								{/each}
							</div>
						{/if}
					</div>
				</div>

				{#if error}
					<p class="text-destructive">{error}</p>
				{/if}

				<Button class="w-full" onclick={handleSave} disabled={saving || deleting || (existingRating !== null && !hasChanges)}>
					{#if saving}
						Saving...
					{:else if existingRating}
						Update Rating
					{:else}
						Submit Rating
					{/if}
				</Button>
			</div>
		{/if}
	</Card.Content>
</Card.Root>
