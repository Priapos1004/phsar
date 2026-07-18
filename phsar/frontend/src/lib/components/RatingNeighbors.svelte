<script lang="ts">
	import { Badge } from '$lib/components/ui/badge';
	import { api } from '$lib/api';
	import { getRatingAttr } from '$lib/types/api';
	import type { RatingScoreItem } from '$lib/types/api';
	import { selectRatingNeighbors } from '$lib/utils/ratingNeighbors';
	import { attributeBadges, compareAttribute, type AttributeComparison } from '$lib/utils/ratingAttributes';
	import { formatScore, resolveTitle } from '$lib/utils/formatString';
	import { userSettings } from '$lib/stores/userSettings';
	import * as cls from '$lib/styles/classes';
	import { ChevronDown, ChevronUp, Star } from 'lucide-svelte';

	interface Props {
		/** The snapped score being assigned — neighbors recompute live as it moves. */
		score: number;
		// Current anime's comparison context: animeUuid is excluded so neighbors come from
		// OTHER anime; genres/studios/age feed the tiebreak.
		animeUuid?: string;
		genres?: string[];
		studios?: string[];
		ageRatingNumeric?: number | null;
		// The user's live in-progress selection — each neighbor attribute is colored by how
		// it compares (green higher / red lower / blue differs / cream match / grey unset).
		// Reactive, so the colors update as the user changes their own picks, not just the score.
		currentAttributes?: Record<string, string | null>;
	}

	let { score, animeUuid, genres = [], studios = [], ageRatingNumeric = null, currentAttributes = {} }: Props = $props();

	const COMPARISON_CLASS: Record<AttributeComparison, string> = {
		higher: cls.badgeAttrHigher,
		lower: cls.badgeAttrLower,
		differs: cls.badgeAttrDiffers,
		match: cls.badgeAttrMatch,
		neutral: cls.badgeAttrNeutral,
	};

	let nameLanguage = $derived($userSettings?.name_language ?? 'english');

	// Fetched once on first expand and cached, so moving the score recomputes the
	// nearby ratings client-side with no extra request.
	let showNeighbors = $state(false);
	let neighborItems = $state<RatingScoreItem[] | null>(null);
	let loadingNeighbors = $state(false);
	let neighborsError = $state(false);
	let expandedNeighbors = $state<Record<string, boolean>>({});

	// Shown high→low so the rows straddle the current score in descending order.
	let neighbors = $derived(
		neighborItems
			? selectRatingNeighbors(neighborItems, score, { animeUuid, genres, studios, ageRatingNumeric })
			: [],
	);
	let neighborRows = $derived([...neighbors].sort((a, b) => b.rating - a.rating));

	async function loadNeighbors() {
		if (loadingNeighbors) return;
		loadingNeighbors = true;
		neighborsError = false;
		try {
			neighborItems = await api.get<RatingScoreItem[]>('/ratings/scores');
		} catch {
			// Leave neighborItems null (not []) so a re-expand or the explicit
			// "Try again" retries instead of latching the misleading empty state.
			neighborsError = true;
		} finally {
			loadingNeighbors = false;
		}
	}

	function toggleNeighbors() {
		showNeighbors = !showNeighbors;
		// loadNeighbors self-guards against a concurrent in-flight fetch.
		if (showNeighbors && neighborItems === null) {
			void loadNeighbors();
		}
	}
</script>

<div>
	<button
		type="button"
		class="flex items-center gap-2 text-primary group"
		onclick={toggleNeighbors}
	>
		{#if showNeighbors}
			<ChevronUp class="size-4" />
		{:else}
			<ChevronDown class="size-4" />
		{/if}
		<span class="group-hover:underline">How you rated similar titles</span>
	</button>

	{#if showNeighbors}
		{#if loadingNeighbors}
			<p class="text-sm text-muted-foreground mt-2">Loading…</p>
		{:else if neighborsError}
			<p class="text-sm text-muted-foreground mt-2">
				Couldn't load your ratings.
				<button type="button" class="text-primary hover:underline" onclick={loadNeighbors}>
					Try again
				</button>
			</p>
		{:else if neighborRows.length === 0}
			<p class="text-sm text-muted-foreground mt-2">
				Rate a few titles from other anime to compare your scores here.
			</p>
		{:else}
			<p class="text-xs text-muted-foreground mt-2">
				Your closest scores from other anime — a nudge toward a consistent scale.
			</p>
			<div class="mt-2 space-y-2">
				{#each neighborRows as n (n.media_uuid)}
					{@const attrs = attributeBadges(n)}
						<!-- Default-expanded when the neighbor has rated attributes — the comparison
						     shows without clicking each row; an explicit toggle overrides. -->
						{@const expanded = expandedNeighbors[n.media_uuid] ?? attrs.length > 0}
					{@const mediaName = resolveTitle(n.media_title, n.media_name_eng, n.media_name_jap, nameLanguage)}
					{@const animeName = resolveTitle(n.anime_title, n.anime_name_eng, n.anime_name_jap, nameLanguage)}
					<div class="rounded-lg border border-border bg-card overflow-hidden">
						<button
							type="button"
							class="w-full flex items-center gap-3 px-3 py-2 text-left hover:bg-muted/40 transition"
							onclick={() => (expandedNeighbors[n.media_uuid] = !expanded)}
						>
							{#if n.media_cover_image}
								<img src={n.media_cover_image} alt="" loading="lazy" class="w-8 h-11 rounded object-cover shrink-0" />
							{/if}
							<div class="flex-1 min-w-0">
								<p class="text-sm font-medium text-card-foreground truncate">{mediaName}</p>
								<p class="text-xs text-muted-foreground truncate">{animeName}</p>
							</div>
							<span class="flex items-center gap-1 text-card-foreground font-bold shrink-0">
								<Star class="size-3.5 text-primary" fill="currentColor" />
								{formatScore(n.rating)}
							</span>
							{#if expanded}
								<ChevronUp class="size-4 text-muted-foreground shrink-0" />
							{:else}
								<ChevronDown class="size-4 text-muted-foreground shrink-0" />
							{/if}
						</button>
						{#if expanded}
							<div class="px-3 pb-2 flex flex-wrap gap-1">
								{#if attrs.length}
									{#each attrs as attr}
										{@const verdict = compareAttribute(attr.key, getRatingAttr(n, attr.key) ?? '', currentAttributes[attr.key] ?? null)}
										<Badge variant="secondary" class="font-normal {COMPARISON_CLASS[verdict]}">{attr.label}: {attr.value}</Badge>
									{/each}
								{:else}
									<span class="text-xs text-muted-foreground">No attributes rated</span>
								{/if}
							</div>
						{/if}
					</div>
				{/each}
			</div>
		{/if}
	{/if}
</div>
