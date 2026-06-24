<script lang="ts">
	import * as Card from '$lib/components/ui/card';
	import * as Dialog from '$lib/components/ui/dialog';
	import { Button } from '$lib/components/ui/button';
	import { Input } from '$lib/components/ui/input';
	import { Label } from '$lib/components/ui/label';
	import { Slider } from '$lib/components/ui/slider';
	import { Textarea } from '$lib/components/ui/textarea';
	import { Badge } from '$lib/components/ui/badge';
	import { api, ApiError } from '$lib/api';
	import { RATING_ATTRIBUTE_OPTIONS, WATCH_STATUS_OPTIONS, getRatingAttr } from '$lib/types/api';
	import type { RatingOut, RatingCreate, WatchStatus } from '$lib/types/api';
	import DeleteWatchHistoryToggle from '$lib/components/DeleteWatchHistoryToggle.svelte';
	import AttributeSelect from '$lib/components/AttributeSelect.svelte';
	import RatingNeighbors from '$lib/components/RatingNeighbors.svelte';
	import { attributeBadges } from '$lib/utils/ratingAttributes';
	import { formatDecimalDigits, clampAndSnapScore, decimalPlaces } from '$lib/utils/formatString';
	import { userSettings } from '$lib/stores/userSettings';
	import * as cls from '$lib/styles/classes';
	import { ChevronDown, ChevronUp, Star, Pencil, Trash2, RotateCcw } from 'lucide-svelte';

	interface Props {
		mediaUuid: string;
		totalEpisodes: number | null;
		existingRating: RatingOut | null;
		onSaved: (rating: RatingOut) => void;
		onDeleted: () => void;
		// Current media's comparison context for the rating-consistency helper.
		animeUuid?: string;
		genres?: string[];
		studios?: string[];
		ageRatingNumeric?: number | null;
	}

	let {
		mediaUuid,
		totalEpisodes,
		existingRating,
		onSaved,
		onDeleted,
		animeUuid,
		genres = [],
		studios = [],
		ageRatingNumeric = null,
	}: Props = $props();


	let editing = $state(false);
	let score = $state<number>(5.0);
	let status = $state<WatchStatus>('completed');
	let episodesWatched = $state<string>('');
	let note = $state('');
	let showAttributes = $state(false);
	let saving = $state(false);
	let deleting = $state(false);
	let deleteOpen = $state(false);
	let deleteHistory = $state(false);
	let loggingRewatch = $state(false);
	let rewatchOpen = $state(false);
	let downgradeOpen = $state(false);
	let error = $state('');
	let attributes = $state<Record<string, string | null>>({});

	// On Hold and Dropped both mean the anime wasn't finished, so the episode
	// input is revealed and the ending fields are treated as unratable for both.
	let revealsEpisodes = $derived(status === 'on_hold' || status === 'dropped');

	// The ending can't be judged on an unfinished watch, so both ending fields are
	// auto-set to the not_applicable sentinel + disabled when on_hold/dropped, and
	// cleared back on completed. One list so the auto-set effect and the disabled
	// prop can't drift.
	const AUTO_NA_FIELDS: string[] = ['ending_type', 'ending_quality'];

	let hasChanges = $derived.by(() => {
		if (!existingRating) return true;
		if (score !== existingRating.rating) return true;
		if (status !== existingRating.watch_status) return true;
		const epVal = episodesWatched ? parseInt(episodesWatched) : null;
		if (epVal !== existingRating.episodes_watched) return true;
		if ((note.trim() || null) !== (existingRating.note ?? null)) return true;
		for (const key of Object.keys(RATING_ATTRIBUTE_OPTIONS)) {
			if ((attributes[key] || null) !== (getRatingAttr(existingRating!, key))) return true;
		}
		return false;
	});

	let filledAttributes = $derived(existingRating ? attributeBadges(existingRating) : []);

	let SCORE_STEP = $derived(parseFloat($userSettings?.rating_step ?? '0.5'));
	// Edit form: precision matches current step (user inputs at this precision)
	let STEP_DECIMALS = $derived(decimalPlaces(SCORE_STEP));
	// Display: enough decimals to accurately show the stored value (may exceed current step)
	let DISPLAY_DECIMALS = $derived(
		existingRating ? Math.max(STEP_DECIMALS, decimalPlaces(existingRating.rating)) : STEP_DECIMALS
	);

	function clampAndSnap(val: number): number {
		return clampAndSnapScore(val, SCORE_STEP);
	}

	let snappedScore = $derived(clampAndSnap(score));
	let setAttrCount = $derived(Object.keys(RATING_ATTRIBUTE_OPTIONS).filter(k => attributes[k]).length);
	let totalAttrCount = Object.keys(RATING_ATTRIBUTE_OPTIONS).length;

	function resetForm() {
		if (existingRating) {
			score = existingRating.rating;
			status = existingRating.watch_status;
			episodesWatched = existingRating.episodes_watched?.toString() ?? '';
			note = existingRating.note ?? '';
			for (const key of Object.keys(RATING_ATTRIBUTE_OPTIONS)) {
				attributes[key] = getRatingAttr(existingRating!, key);
			}
		} else {
			score = 5.0;
			status = 'completed';
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
		// Only auto-fill episodes when creating a new rating (not editing existing)
		if (!existingRating && !revealsEpisodes && totalEpisodes !== null) {
			episodesWatched = totalEpisodes.toString();
		}
	});

	$effect(() => {
		// On hold / dropped → ending fields aren't ratable; completed → clear auto-set value
		for (const key of AUTO_NA_FIELDS) {
			if (revealsEpisodes) {
				attributes[key] = 'not_applicable';
			} else if (attributes[key] === 'not_applicable') {
				attributes[key] = null;
			}
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

	// True when saving would turn a previously-completed rating (with recorded watches)
	// into on_hold/dropped — the point where we must ask about the now-orphaned history.
	let isDowngradingWithHistory = $derived(
		!!existingRating &&
		existingRating.watch_status === 'completed' &&
		status !== 'completed' &&
		existingRating.watched_count > 0,
	);

	function handleSave() {
		// Intercept a downgrade that would strand watch history — confirm keep vs remove first.
		if (isDowngradingWithHistory) {
			downgradeOpen = true;
			return;
		}
		doSave(false);
	}

	async function doSave(deleteWatchHistory: boolean) {
		saving = true;
		error = '';

		const attrFields: Record<string, string | null> = {};
		for (const key of Object.keys(RATING_ATTRIBUTE_OPTIONS)) {
			attrFields[key] = attributes[key] || null;
		}

		const payload: RatingCreate = {
			rating: snappedScore,
			watch_status: status,
			episodes_watched: episodesWatched ? parseInt(episodesWatched) : null,
			note: note.trim() || null,
			...attrFields,
		};

		try {
			const qs = deleteWatchHistory ? '?delete_watch_history=true' : '';
			const result = await api.put<RatingOut>(`/ratings/media/${mediaUuid}${qs}`, payload);
			onSaved(result);
			editing = false;
			downgradeOpen = false;
		} catch (err) {
			error = err instanceof ApiError ? err.detail : 'Failed to save rating';
		} finally {
			saving = false;
		}
	}

	function requestDelete() {
		deleteHistory = false;
		deleteOpen = true;
	}

	async function handleDelete() {
		if (!existingRating) return;
		deleting = true;
		error = '';

		try {
			const qs = deleteHistory ? '?delete_watch_history=true' : '';
			await api.del(`/ratings/${existingRating.uuid}${qs}`);
			onDeleted();
			editing = false;
			deleteOpen = false;
		} catch (err) {
			error = err instanceof ApiError ? err.detail : 'Failed to delete rating';
		} finally {
			deleting = false;
		}
	}

	async function handleRewatch() {
		if (!existingRating) return;
		loggingRewatch = true;
		error = '';

		try {
			const updated = await api.post<RatingOut>(`/ratings/${existingRating.uuid}/rewatch`, {});
			onSaved(updated);
			rewatchOpen = false;
		} catch (err) {
			error = err instanceof ApiError ? err.detail : 'Failed to log rewatch';
		} finally {
			loggingRewatch = false;
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
					<div class="flex gap-1.5 items-center flex-wrap justify-end">
						<Button variant="secondary" size="sm" onclick={startEditing}>
							<Pencil class="size-3.5 mr-1" /> Edit
						</Button>
						{#if existingRating.watch_status === 'completed'}
							<Button variant="secondary" size="sm" onclick={() => (rewatchOpen = true)}>
								<RotateCcw class="size-3.5 mr-1" /> Rewatch
							</Button>
						{/if}
						<Button variant="destructive" size="sm" onclick={requestDelete}>
							<Trash2 class="size-3.5 mr-1" /> Delete
						</Button>
					</div>
				</div>

				<div class="flex items-center gap-4">
					<div class="w-16 h-16 rounded-full bg-primary/10 border-2 border-primary/30 flex items-center justify-center shrink-0">
						<span class="text-xl font-bold text-card-foreground">
							{formatDecimalDigits(existingRating.rating, DISPLAY_DECIMALS)}
						</span>
					</div>
					<div class="space-y-1">
						<div class="flex items-center gap-2">
							{#if existingRating.watch_status === 'dropped'}
								<Badge variant="destructive">Dropped</Badge>
							{:else if existingRating.watch_status === 'on_hold'}
								<Badge variant="secondary" class={cls.badgeOnHold}>On Hold</Badge>
							{:else}
								<span class="text-card-foreground font-medium">Completed</span>
							{/if}
							{#if existingRating.episodes_watched !== null}
								<span class="text-muted-foreground">
									· {existingRating.episodes_watched}{totalEpisodes ? `/${totalEpisodes}` : ''} eps
								</span>
							{/if}
							{#if existingRating.watched_count > 1}
								<Badge variant="secondary">Watched {existingRating.watched_count}×</Badge>
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
							value={snappedScore.toFixed(STEP_DECIMALS)}
							onblur={(e) => {
								const parsed = parseFloat(e.currentTarget.value.replace(',', '.')) || 0;
								score = clampAndSnap(parsed);
								e.currentTarget.value = clampAndSnap(parsed).toFixed(STEP_DECIMALS);
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
					<!-- Watch status (segmented) + Episodes -->
					<div class="flex items-center gap-4 flex-wrap">
						<div class="flex items-center gap-2">
							<Label>Status</Label>
							<div class="inline-flex rounded-md border border-border overflow-hidden">
								{#each WATCH_STATUS_OPTIONS as opt}
									<Button
										type="button"
										variant={status === opt.value ? 'default' : 'ghost'}
										size="sm"
										class="rounded-none border-0"
										onclick={() => { status = opt.value; }}
									>
										{opt.label}
									</Button>
								{/each}
							</div>
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
								disabled={!revealsEpisodes && totalEpisodes !== null}
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
									<AttributeSelect
										label={config.label}
										options={config.options}
										value={attributes[key] ?? null}
										onChange={(v) => (attributes[key] = v)}
										disabled={AUTO_NA_FIELDS.includes(key) && revealsEpisodes}
									/>
								{/each}
							</div>
						{/if}
					</div>
				</div>

				<!-- Rating-consistency helper: how you rated nearby-scored titles from other
				     anime, so the user can keep their scale consistent. -->
				<RatingNeighbors score={snappedScore} {animeUuid} {genres} {studios} {ageRatingNumeric} currentAttributes={attributes} />

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

<!-- Rewatch confirm — a pop-up (not an inline button) so the action + its consequence are explicit -->
<Dialog.Root bind:open={rewatchOpen}>
	<Dialog.Content class="sm:max-w-md">
		<Dialog.Header>
			<Dialog.Title>Log a rewatch?</Dialog.Title>
			<Dialog.Description class="text-muted-foreground">
				This records that you finished this anime again (dated today) and raises your watch
				count from {existingRating?.watched_count ?? 0} to {(existingRating?.watched_count ?? 0) + 1}.
				It feeds your watch history and future recommendations, and can't be easily undone.
			</Dialog.Description>
		</Dialog.Header>
		{#if error}<p class="text-destructive text-sm">{error}</p>{/if}
		<Dialog.Footer>
			<Button variant="secondary" onclick={() => (rewatchOpen = false)} disabled={loggingRewatch}>
				Cancel
			</Button>
			<Button onclick={handleRewatch} disabled={loggingRewatch}>
				{loggingRewatch ? 'Logging...' : 'Log rewatch'}
			</Button>
		</Dialog.Footer>
	</Dialog.Content>
</Dialog.Root>

<!-- Delete confirm — with an explicit, explained watch-history choice -->
<Dialog.Root bind:open={deleteOpen}>
	<Dialog.Content class="sm:max-w-md">
		<Dialog.Header>
			<Dialog.Title>Delete this rating?</Dialog.Title>
			<Dialog.Description class="text-muted-foreground">
				Your score, note, and attributes for this media will be removed. This can't be undone.
			</Dialog.Description>
		</Dialog.Header>
		{#if existingRating && existingRating.watched_count > 0}
			<DeleteWatchHistoryToggle
				bind:checked={deleteHistory}
				detail="You have {existingRating.watched_count} recorded watch{existingRating.watched_count > 1 ? 'es' : ''}."
			/>
		{/if}
		{#if error}<p class="text-destructive text-sm">{error}</p>{/if}
		<Dialog.Footer>
			<Button variant="secondary" onclick={() => (deleteOpen = false)} disabled={deleting}>
				Cancel
			</Button>
			<Button variant="destructive" onclick={handleDelete} disabled={deleting}>
				{deleting ? 'Deleting...' : 'Delete rating'}
			</Button>
		</Dialog.Footer>
	</Dialog.Content>
</Dialog.Root>

<!-- Downgrade confirm — completed → on_hold/dropped while watch history exists -->
<Dialog.Root bind:open={downgradeOpen}>
	<Dialog.Content class="sm:max-w-md">
		<Dialog.Header>
			<Dialog.Title>Keep your watch history?</Dialog.Title>
			<Dialog.Description class="text-muted-foreground">
				You're changing this from Completed to
				{WATCH_STATUS_OPTIONS.find((o) => o.value === status)?.label ?? status}.
				{#if existingRating}
					You have {existingRating.watched_count} recorded watch{existingRating.watched_count > 1 ? 'es' : ''}.
				{/if}
				Keep them if you finished it before (e.g. you're rewatching and paused), or remove them if
				you hadn't really completed it.
			</Dialog.Description>
		</Dialog.Header>
		{#if error}<p class="text-destructive text-sm">{error}</p>{/if}
		<Dialog.Footer>
			<Button variant="secondary" onclick={() => (downgradeOpen = false)} disabled={saving}>
				Cancel
			</Button>
			<Button variant="destructive" onclick={() => doSave(true)} disabled={saving}>
				Remove history
			</Button>
			<Button onclick={() => doSave(false)} disabled={saving}>
				Keep history
			</Button>
		</Dialog.Footer>
	</Dialog.Content>
</Dialog.Root>
