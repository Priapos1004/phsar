<script lang="ts">
	import * as Dialog from '$lib/components/ui/dialog';
	import * as Select from '$lib/components/ui/select';
	import { Button } from '$lib/components/ui/button';
	import { Checkbox } from '$lib/components/ui/checkbox';
	import { Input } from '$lib/components/ui/input';
	import { Label } from '$lib/components/ui/label';
	import { Slider } from '$lib/components/ui/slider';
	import { Textarea } from '$lib/components/ui/textarea';
	import { api, ApiError } from '$lib/api';
	import { RATING_ATTRIBUTE_OPTIONS } from '$lib/types/api';
	import type { RatingOut, RatingCreate } from '$lib/types/api';
	import { ChevronDown, ChevronUp } from 'lucide-svelte';

	interface Props {
		open: boolean;
		mediaUuid: string;
		mediaTitle: string;
		totalEpisodes: number | null;
		existingRating: RatingOut | null;
		onSaved: (rating: RatingOut) => void;
		onDeleted: () => void;
	}

	let {
		open = $bindable(),
		mediaUuid,
		mediaTitle,
		totalEpisodes,
		existingRating,
		onSaved,
		onDeleted,
	}: Props = $props();

	let score = $state<number>(5.0);
	let dropped = $state(false);
	let episodesWatched = $state<string>('');
	let note = $state('');
	let showAttributes = $state(false);
	let saving = $state(false);
	let deleting = $state(false);
	let error = $state('');
	let attributes = $state<Record<string, string | null>>({});

	$effect(() => {
		if (existingRating) {
			score = existingRating.rating;
			dropped = existingRating.dropped;
			episodesWatched = existingRating.episodes_watched?.toString() ?? '';
			note = existingRating.note ?? '';
			for (const key of Object.keys(RATING_ATTRIBUTE_OPTIONS)) {
				attributes[key] = (existingRating as unknown as Record<string, string | null>)[key] ?? null;
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
	});

	function snapScore(val: number): number {
		return Math.round(val * 2) / 2;
	}

	async function handleSave() {
		saving = true;
		error = '';

		const payload: RatingCreate = {
			rating: snapScore(score),
			dropped,
			episodes_watched: episodesWatched ? parseInt(episodesWatched) : null,
			note: note.trim() || null,
		};

		for (const key of Object.keys(RATING_ATTRIBUTE_OPTIONS)) {
			(payload as unknown as Record<string, string | null>)[key] = attributes[key] || null;
		}

		try {
			const result = await api.put<RatingOut>(`/ratings/media/${mediaUuid}`, payload);
			onSaved(result);
			open = false;
		} catch (err) {
			error = err instanceof ApiError ? err.detail : 'Failed to save rating';
		} finally {
			saving = false;
		}
	}

	async function handleDelete() {
		if (!existingRating) return;
		deleting = true;
		error = '';

		try {
			await api.del(`/ratings/${existingRating.uuid}`);
			onDeleted();
			open = false;
		} catch (err) {
			error = err instanceof ApiError ? err.detail : 'Failed to delete rating';
		} finally {
			deleting = false;
		}
	}
</script>

<Dialog.Root bind:open>
	<Dialog.Content class="sm:max-w-lg max-h-[85vh] overflow-y-auto">
		<Dialog.Header>
			<Dialog.Title>
				{existingRating ? 'Edit Rating' : 'Rate'}: {mediaTitle}
			</Dialog.Title>
		</Dialog.Header>

		<div class="space-y-5">
			<div class="space-y-2">
				<Label>Score: {snapScore(score).toFixed(1)}</Label>
				<Slider type="single" bind:value={score} min={0} max={10} step={0.5} />
				<div class="flex justify-between text-xs text-muted-foreground">
					<span>0</span>
					<span>5</span>
					<span>10</span>
				</div>
			</div>

			<div class="flex items-center gap-2">
				<Checkbox
					checked={dropped}
					onCheckedChange={(val: boolean | 'indeterminate') => { dropped = val === true; }}
				/>
				<Label>Dropped</Label>
			</div>

			<div class="space-y-1">
				<Label>
					Episodes watched
					{#if totalEpisodes !== null}
						<span class="text-muted-foreground font-normal">/ {totalEpisodes}</span>
					{/if}
				</Label>
				<Input
					type="number"
					min={0}
					max={totalEpisodes ?? undefined}
					bind:value={episodesWatched}
					placeholder="e.g. 12"
				/>
			</div>

			<div class="space-y-1">
				<Label>Note <span class="text-muted-foreground font-normal">({note.length}/1000)</span></Label>
				<Textarea
					bind:value={note}
					maxlength={1000}
					rows={3}
					placeholder="Your thoughts on this anime..."
				/>
			</div>

			<div>
				<button
					type="button"
					class="flex items-center gap-1 text-sm text-primary hover:underline"
					onclick={() => (showAttributes = !showAttributes)}
				>
					{#if showAttributes}
						<ChevronUp class="size-4" /> Hide details
					{:else}
						<ChevronDown class="size-4" /> Show details
					{/if}
				</button>

				{#if showAttributes}
					<div class="grid grid-cols-2 gap-3 mt-3">
						{#each Object.entries(RATING_ATTRIBUTE_OPTIONS) as [key, config]}
							<div class="space-y-1">
								<Label class="text-xs">{config.label}</Label>
								<Select.Root
									type="single"
									value={attributes[key] ?? undefined}
									onValueChange={(val: string) => { attributes[key] = val || null; }}
								>
									<Select.Trigger class="w-full text-xs">
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

			{#if error}
				<p class="text-sm text-destructive">{error}</p>
			{/if}
		</div>

		<Dialog.Footer class="flex gap-2 pt-4">
			{#if existingRating}
				<Button
					variant="destructive"
					onclick={handleDelete}
					disabled={deleting || saving}
				>
					{deleting ? 'Deleting...' : 'Delete'}
				</Button>
			{/if}
			<div class="flex-1"></div>
			<Button variant="outline" onclick={() => { open = false; }} disabled={saving || deleting}>
				Cancel
			</Button>
			<Button onclick={handleSave} disabled={saving || deleting}>
				{saving ? 'Saving...' : 'Save'}
			</Button>
		</Dialog.Footer>
	</Dialog.Content>
</Dialog.Root>
