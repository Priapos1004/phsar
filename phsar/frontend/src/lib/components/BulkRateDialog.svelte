<script lang="ts">
	import * as Dialog from '$lib/components/ui/dialog';
	import * as Select from '$lib/components/ui/select';
	import { Button } from '$lib/components/ui/button';
	import { Label } from '$lib/components/ui/label';
	import { Slider } from '$lib/components/ui/slider';
	import { Textarea } from '$lib/components/ui/textarea';
	import { ChevronDown, ChevronUp } from 'lucide-svelte';
	import { clampAndSnapScore, decimalPlaces } from '$lib/utils/formatString';
	import { RATING_ATTRIBUTE_OPTIONS } from '$lib/types/api';
	import type { RatingOut } from '$lib/types/api';
	import { api, ApiError } from '$lib/api';
	import { userSettings } from '$lib/stores/userSettings';

	interface Props {
		open: boolean;
		selectedUuids: Set<string>;
		alreadyRatedCount: number;
		onSaved: (results: RatingOut[], note: string) => void;
	}

	let {
		open = $bindable(),
		selectedUuids,
		alreadyRatedCount,
		onSaved,
	}: Props = $props();

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
	<Dialog.Content class="bg-card text-card-foreground max-h-[85vh] overflow-y-auto sm:max-w-md">
		<Dialog.Header>
			<Dialog.Title class="text-card-foreground">Rate {selectedUuids.size} Media</Dialog.Title>
			<Dialog.Description class="text-muted-foreground">
				Score and attributes are applied to all selected media.
			</Dialog.Description>
		</Dialog.Header>

		<div class="space-y-4 py-2">
			{#if alreadyRatedCount > 0}
				<div class="rounded-lg border border-yellow-200 bg-yellow-50 px-3 py-2 text-sm text-yellow-800">
					This will overwrite {alreadyRatedCount} existing rating{alreadyRatedCount > 1 ? 's' : ''}.
				</div>
			{/if}

			<!-- Score: editable circle + slider -->
			<div class="flex flex-col items-center py-2 space-y-3">
				<div class="w-20 h-20 rounded-full bg-primary/10 border-2 border-primary/30 flex items-center justify-center">
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
						class="w-14 text-center text-2xl font-bold text-card-foreground bg-transparent outline-none"
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
					<p class="text-xs text-muted-foreground">Applied to the last main media only.</p>
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
								<div class="space-y-1">
									<Label class={attributes[key] ? 'text-card-foreground font-medium' : 'text-muted-foreground'}>
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

			<Button class="w-full" onclick={handleSave} disabled={saving}>
				{#if saving}
					Saving...
				{:else}
					Rate {selectedUuids.size} Media
				{/if}
			</Button>
		</div>
	</Dialog.Content>
</Dialog.Root>
