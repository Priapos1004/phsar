<script lang="ts">
	// The filter sheet's genre field: groups of "any or all of these, none of those", joined
	// by any or all (`GenreFilter`, whose backend docstring says why one level of groups is
	// enough). One group reads as a plain field with a Without row; a second turns each
	// group into a card. What the user picks runs as picked — only a group with nothing in
	// it goes — so a contradiction, a tautology or a group that changes nothing is said out
	// loud (`checkGenres`) rather than simplified away, which would make blocks vanish from
	// the user's search.
	import { Plus, X } from 'lucide-svelte';
	import ExpressionText from '$lib/components/ExpressionText.svelte';
	import Notice from '$lib/components/Notice.svelte';
	import SegmentedControl from '$lib/components/SegmentedControl.svelte';
	import TagSelect from '$lib/components/TagSelect.svelte';
	import * as cls from '$lib/styles/classes';
	import {
		MATCH_MODES,
		MAX_GENRE_GROUPS,
		checkGenres,
		describeGenreTerms,
		isEmptyGroup,
		type GenreFilter,
		type GenreGroup,
	} from '$lib/utils/search';

	interface Props {
		value: GenreFilter | null | undefined;
		options: string[];
		onChange: (value: GenreFilter) => void;
	}

	let { value, options, onChange }: Props = $props();

	const EMPTY_GROUP: GenreGroup = { mode: 'all', include: [], exclude_mode: 'any', exclude: [] };
	const JOIN_MODES = [{ value: 'any' as const, label: 'Any group' }, { value: 'all' as const, label: 'All groups' }];
	const subLabelCls = 'text-xs text-card-foreground/70';

	let genres = $derived<GenreFilter>(value?.groups.length ? value : { mode: 'any', groups: [EMPTY_GROUP] });
	let several = $derived(genres.groups.length > 1);
	let reads = $derived(describeGenreTerms(genres));
	let check = $derived(checkGenres(genres));
	let addButton: HTMLButtonElement | undefined = $state();

	const setGroup = (at: number, patch: Partial<GenreGroup>) =>
		onChange({ ...genres, groups: genres.groups.map((g, i) => (i === at ? { ...g, ...patch } : g)) });

	function removeGroup(at: number) {
		// The ✕ leaves with its card, so focus moves to a control that stays first.
		addButton?.focus();
		onChange({ ...genres, groups: genres.groups.filter((_, i) => i !== at) });
	}
</script>

{#snippet modeControl(group: GenreGroup, at: number, key: 'mode' | 'exclude_mode')}
	{@const what = key === 'mode' ? 'match' : 'without'}
	<SegmentedControl
		ariaLabel={several ? `Group ${at + 1} ${what} mode` : `Genres ${what} mode`}
		options={MATCH_MODES}
		value={group[key]}
		onSelect={(mode) => setGroup(at, { [key]: mode })}
	/>
{/snippet}

{#snippet lists(group: GenreGroup, at: number)}
	<TagSelect
		placeholder="Add genres..."
		options={options.filter((o) => !group.exclude.includes(o))}
		selectedItems={group.include}
		onAdd={(item) => setGroup(at, { include: [...group.include, item] })}
		onRemove={(item) => setGroup(at, { include: group.include.filter((i) => i !== item) })}
	/>
	<div class="flex h-6 items-center justify-between">
		<span class={subLabelCls}>Without</span>
		{@render modeControl(group, at, 'exclude_mode')}
	</div>
	<TagSelect
		placeholder="Exclude genres..."
		options={options.filter((o) => !group.include.includes(o))}
		selectedItems={group.exclude}
		onAdd={(item) => setGroup(at, { exclude: [...group.exclude, item] })}
		onRemove={(item) => setGroup(at, { exclude: group.exclude.filter((i) => i !== item) })}
	/>
{/snippet}

<div class="space-y-1.5">
	<div class="flex h-6 items-center justify-between">
		<span class={cls.fieldLabel}>Genres</span>
		{#if several}
			<SegmentedControl
				ariaLabel="Genre groups match mode"
				options={JOIN_MODES}
				value={genres.mode}
				onSelect={(mode) => onChange({ ...genres, mode })}
			/>
		{:else}
			{@render modeControl(genres.groups[0], 0, 'mode')}
		{/if}
	</div>

	{#if several}
		{#each genres.groups as group, at (at)}
			{#if at > 0}
				<p class="text-center text-xs font-semibold uppercase tracking-wide text-primary">
					{genres.mode === 'all' ? 'and' : 'or'}
				</p>
			{/if}
			<div class="space-y-1.5 rounded-lg border border-border p-3" data-testid="genre-group">
				<div class="flex h-6 items-center justify-between gap-2">
					{#if isEmptyGroup(group)}
						<span class={subLabelCls}>Empty — ignored</span>
					{:else if check.idle.includes(at)}
						<span class="text-xs font-medium text-amber-700">Group {at + 1} · changes nothing</span>
					{:else}
						<span class={subLabelCls}>Group {at + 1}</span>
					{/if}
					<div class="flex items-center gap-2">
						{@render modeControl(group, at, 'mode')}
						<button
							type="button"
							class="relative text-card-foreground/70 hover:text-card-foreground {cls.hitArea}"
							aria-label="Remove group {at + 1}"
							onclick={() => removeGroup(at)}
						>
							<X class="size-3.5" />
						</button>
					</div>
				</div>
				{@render lists(group, at)}
			</div>
		{/each}
	{:else}
		{@render lists(genres.groups[0], 0)}
	{/if}

	<button
		bind:this={addButton}
		type="button"
		class="inline-flex items-center gap-1 text-sm text-primary hover:underline disabled:opacity-50 disabled:no-underline"
		disabled={genres.groups.length >= MAX_GENRE_GROUPS}
		onclick={() => onChange({ ...genres, groups: [...genres.groups, EMPTY_GROUP] })}
	>
		<Plus class="size-3.5" /> Add a group
	</button>

	{#if reads.length}
		<p class={subLabelCls}>Reads: <ExpressionText parts={reads} keywordClass="font-semibold text-primary" /></p>
	{/if}
	{#if check.warning}<Notice>{check.warning}</Notice>{/if}
</div>
