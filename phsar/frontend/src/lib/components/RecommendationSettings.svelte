<script lang="ts">
	// The settings page's Recommendations card: the settings that tune what the recommender
	// learns from (docs/features/recommender.md). The history start's picker
	// follows the admin Completion card's search — covers, a button per row — with the start in
	// use pinned above it, so a search can be compared against it. It stays folded behind
	// Change until wanted: a list of every rating is a lot to show.
	import { untrack } from 'svelte';
	import { api, ApiError } from '$lib/api';
	import * as Card from '$lib/components/ui/card';
	import { Button } from '$lib/components/ui/button';
	import { Label } from '$lib/components/ui/label';
	import { Separator } from '$lib/components/ui/separator';
	import { Switch } from '$lib/components/ui/switch';
	import InfoTip from '$lib/components/InfoTip.svelte';
	import SearchInput from '$lib/components/SearchInput.svelte';
	import { Check } from 'lucide-svelte';
	import * as cls from '$lib/styles/classes';
	import { dropPersonalRows } from '$lib/stores/browseRows';
	import { pushToast } from '$lib/stores/toast';
	import type { HistoryStart, HistoryStartRating, UserSettings, UserSettingsUpdate } from '$lib/types/api';
	import { formatShortDate, resolveTitle } from '$lib/utils/formatString';

	interface Props {
		settings: UserSettings;
		isRestricted: boolean;
		onSave: (update: UserSettingsUpdate) => unknown;
	}

	let { settings, isRestricted, onSave }: Props = $props();

	let start = $state<HistoryStart | null>(null);
	let open = $state(false);
	let query = $state('');
	let toggle = $state<HTMLButtonElement | null>(null);
	let list = $state<HTMLElement | null>(null);

	// A guest has no ratings, and the endpoint refuses them.
	$effect(() => {
		if (isRestricted) return;
		api.get<HistoryStart>('/ratings/history-start').then((s) => (start = s), () => {});
	});

	const title = (r: HistoryStartRating) => resolveTitle(r.title, r.name_eng, r.name_jap, settings.name_language);

	// A pick of the detected rating is no pick: the start follows the detection again.
	const asPick = (uuid: string | null | undefined) => (uuid === start?.detected ? null : (uuid ?? null));

	// Newest first: scrolling down walks back through the history, past the start into the
	// ratings it leaves out.
	let ratings = $derived(start ? [...start.ratings].reverse() : []);
	const find = (uuid: string | null | undefined) => ratings.find((r) => r.uuid === uuid);
	let chosen = $derived(find(asPick(start?.chosen)));
	let current = $derived(chosen ?? find(start?.detected));
	let currentIndex = $derived(current ? ratings.indexOf(current) : -1);

	// Each row's title and day, worked out once rather than on every keystroke of a search.
	let named = $derived(ratings.map((r) => ({ r, name: title(r), day: formatShortDate(r.at) })));

	// Day headings in the viewer's zone, as each rating's date reads; a search keeps the days
	// it matches in.
	let days = $derived.by(() => {
		const q = query.trim().toLowerCase();
		const out: { day: string; rows: { r: HistoryStartRating; name: string; older: boolean }[] }[] = [];
		named.forEach(({ r, name, day }, i) => {
			if (q && !name.toLowerCase().includes(q)) return;
			const row = { r, name, older: currentIndex >= 0 && i > currentIndex };
			if (out.at(-1)?.day === day) out.at(-1)!.rows.push(row);
			else out.push({ day, rows: [row] });
		});
		return out;
	});

	// The list folds away after a pick, taking the clicked button with it, so focus moves to
	// Change first; "Use detected" leaves the same way (rules/frontend.md, "A control that
	// removes itself hands focus on first").
	async function choose(uuid: string | null) {
		toggle?.focus();
		open = false;
		const pick = asPick(uuid);
		if (!start || pick === asPick(start.chosen)) return;
		try {
			start = await api.put<HistoryStart>('/ratings/history-start', { rating: pick });
			dropPersonalRows(); // the ranking reads the start
			pushToast('Settings updated');
		} catch (err) {
			pushToast(err instanceof ApiError ? err.detail : 'Failed to save settings.', 'error');
		}
	}

	// Each time the list opens, at the start rather than at the newest rating. Within the list
	// only, so the page stays put.
	$effect(() => {
		if (!list) return;
		const at = untrack(() => current);
		const row = at && list.querySelector<HTMLElement>(`[data-uuid="${at.uuid}"]`);
		if (row) list.scrollTop = row.offsetTop - list.clientHeight / 2;
	});
</script>

{#snippet cover(r: HistoryStartRating)}
	{#if r.cover_image}
		<img src={r.cover_image} alt="" class="w-9 h-12 rounded object-cover shrink-0 bg-muted" loading="lazy" />
	{:else}
		<div class="w-9 h-12 rounded bg-muted shrink-0"></div>
	{/if}
{/snippet}

<Card.Root>
	<Card.Header>
		<h2 class="text-lg font-semibold text-card-foreground">Recommendations</h2>
		<p class="text-sm text-muted-foreground">
			{isRestricted ? 'Guest accounts get no recommendations' : 'What your recommendations learn from'}
		</p>
	</Card.Header>
	<Card.Content class="space-y-5">
		<div class="space-y-3">
			<div>
				<div class="flex items-center gap-1.5">
					<Label>Rating history starts</Label>
					<InfoTip
						label="Where your rating history starts"
						text="Phsar's recommendations learn the order you watch anime in from this rating on. It separates the ratings you added for your past, often many at once when you joined, from the ones you add as you watch. Ratings before it still count for your taste. It is detected for you; pick another rating if the detection is off."
					/>
				</div>
				{#if isRestricted}
					<p class="text-xs text-muted-foreground mt-0.5">Off for guest accounts</p>
				{/if}
			</div>

			{#if !isRestricted}
				{#if !start}
					<p class="text-sm text-muted-foreground">Loading your ratings…</p>
				{:else if !ratings.length}
					<p class="text-sm text-muted-foreground">It starts at your first rating.</p>
				{:else}
					<!-- The start in use, kept in view while searching to compare against. On a
					     phone its buttons take a line of their own, so the title keeps the width. -->
					<div class="flex flex-wrap items-center gap-3 rounded-lg border border-border px-3 py-2">
						{#if current}
							{@render cover(current)}
							<div class="flex-1 min-w-0">
								<p class="text-sm font-medium text-card-foreground truncate" title={title(current)}>
									{title(current)}
								</p>
								<p class="text-xs text-muted-foreground">
									{formatShortDate(current.at)} · {chosen ? 'your pick' : 'detected'}
								</p>
							</div>
						{:else}
							<p class="flex-1 text-sm text-muted-foreground">None detected yet: pick the rating it starts at.</p>
						{/if}
						<div class="flex shrink-0 gap-2 max-sm:w-full max-sm:*:flex-1">
							{#if chosen}
								<Button size="sm" variant="secondary" onclick={() => choose(null)}>Use detected</Button>
							{/if}
							<!-- Floored at the wider label's width, so Change ↔ Close never reflows the row. -->
							<Button
								bind:ref={toggle}
								size="sm"
								variant="secondary"
								class="min-w-20"
								aria-expanded={open}
								onclick={() => (open = !open)}
							>
								{open ? 'Close' : 'Change'}
							</Button>
						</div>
					</div>

					{#if open}
						<SearchInput bind:value={query} placeholder="Search your ratings…" />

						<div bind:this={list} class="relative rounded-lg border border-border max-h-80 overflow-y-auto">
							{#each days as { day, rows } (day)}
								<p class="sticky top-0 z-10 bg-card border-b border-border px-3 py-1 text-xs font-medium text-muted-foreground">
									{day}
								</p>
								{#each rows as { r, name, older } (r.uuid)}
									<div data-uuid={r.uuid} class="flex items-center gap-3 px-3 py-2 border-b border-border last:border-b-0">
										<!-- Older than the start: outside the order the recommendations learn. -->
										<div class="flex flex-1 min-w-0 items-center gap-3" class:opacity-50={older}>
											{@render cover(r)}
											<span class="text-sm text-card-foreground truncate" title={name}>{name}</span>
											{#if chosen && r.uuid === start.detected}
												<span class="{cls.mutedPill} shrink-0">detected</span>
											{/if}
										</div>
										{#if r.uuid === current?.uuid}
											<span class="inline-flex items-center gap-1 text-xs font-medium text-primary shrink-0">
												<Check class="size-3.5" /> Start
											</span>
										{:else}
											<Button size="sm" variant="secondary" class="shrink-0" onclick={() => choose(r.uuid)}>
												Start here
											</Button>
										{/if}
									</div>
								{/each}
							{:else}
								<p class="px-3 py-2 text-sm text-muted-foreground">No matching rating.</p>
							{/each}
						</div>
					{/if}
				{/if}
			{/if}
		</div>

		<Separator />

		<div class="flex items-center justify-between gap-4">
			<div>
				<div class="flex items-center gap-1.5">
					<Label for="recommend-hot">Recommend hot anime</Label>
					<InfoTip
						label="What counts as hot"
						text="Hot is the watchlist's word for an anime airing now, or with a new season due next season. Turned off, your recommendations leave those out."
					/>
				</div>
				<p class="text-xs text-muted-foreground mt-0.5">
					{isRestricted ? 'Off for guest accounts' : 'Airing now, or a new season due next season'}
				</p>
			</div>
			<Switch
				id="recommend-hot"
				checked={settings.recommend_hot}
				disabled={isRestricted}
				onCheckedChange={(v) => onSave({ recommend_hot: v })}
			/>
		</div>
	</Card.Content>
</Card.Root>
