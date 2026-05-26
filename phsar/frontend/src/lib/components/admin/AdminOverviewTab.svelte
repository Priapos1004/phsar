<script lang="ts">
	import { onMount } from 'svelte';
	import { api, ApiError } from '$lib/api';
	import * as Card from '$lib/components/ui/card';
	import { formatJobKind, formatNumber } from '$lib/utils/formatString';
	import { librarySaved, onBump } from '$lib/stores/jobs';
	import type { AdminOverviewStats } from '$lib/types/api';

	let stats = $state<AdminOverviewStats | null>(null);
	let loading = $state(true);
	let error = $state('');

	async function load() {
		try {
			stats = await api.get<AdminOverviewStats>('/admin/stats/overview');
			error = '';
		} catch (err) {
			error = err instanceof ApiError ? err.detail : 'Failed to load stats';
		} finally {
			loading = false;
		}
	}

	onMount(load);

	// Refetch when the bell observes a new succeeded user_scrape — catalog
	// counts and the activity panel shift, and the admin shouldn't have to
	// reload to see them. Same pattern as the /library/add recent-additions
	// panel uses to stay current without manual refresh.
	$effect(() => onBump(librarySaved, () => void load()));
</script>

<div class="space-y-6">
	{#if loading}
		<p class="text-white/60 text-sm">Loading stats…</p>
	{:else if error}
		<p class="text-destructive text-sm">{error}</p>
	{:else if stats}
		<Card.Root>
			<Card.Header>
				<h2 class="text-lg font-semibold text-card-foreground">Catalog</h2>
			</Card.Header>
			<Card.Content>
				<div class="grid grid-cols-2 md:grid-cols-4 gap-4">
					<div>
						<div class="text-2xl font-bold text-card-foreground">{formatNumber(stats.catalog.anime_count)}</div>
						<div class="text-xs text-muted-foreground">Anime</div>
					</div>
					<div>
						<div class="text-2xl font-bold text-card-foreground">{formatNumber(stats.catalog.media_count)}</div>
						<div class="text-xs text-muted-foreground">Media</div>
					</div>
					<div>
						<div class="text-2xl font-bold text-primary">+{formatNumber(stats.catalog.anime_added_7d)}</div>
						<div class="text-xs text-muted-foreground">Anime added (7d)</div>
					</div>
					<div>
						<div class="text-2xl font-bold text-primary">+{formatNumber(stats.catalog.media_added_7d)}</div>
						<div class="text-xs text-muted-foreground">Media added (7d)</div>
					</div>
				</div>
			</Card.Content>
		</Card.Root>

		<Card.Root>
			<Card.Header>
				<h2 class="text-lg font-semibold text-card-foreground">Job health (7d)</h2>
			</Card.Header>
			<Card.Content>
				<div class="space-y-3">
					{#each stats.jobs_7d.by_kind as row}
						{@const total = row.succeeded + row.failed}
						{@const successRate = total > 0 ? Math.round((row.succeeded / total) * 100) : null}
						<div class="flex items-center justify-between gap-4 text-sm">
							<div class="flex-1 min-w-0">
								<div class="text-card-foreground font-medium">{formatJobKind(row.kind)}</div>
								<div class="text-xs text-muted-foreground">
									{row.succeeded} ok · {row.failed} failed{#if row.retryable_failed > 0} ({row.retryable_failed} retryable){/if}
								</div>
							</div>
							{#if successRate !== null}
								<div class="shrink-0 w-14 text-right text-sm font-semibold tabular-nums {successRate >= 90 ? 'text-emerald-400' : successRate >= 75 ? 'text-amber-400' : 'text-destructive'}">
									{successRate}%
								</div>
							{:else}
								<div class="shrink-0 w-14 text-right text-xs text-muted-foreground tabular-nums">—</div>
							{/if}
						</div>
					{/each}
				</div>
			</Card.Content>
		</Card.Root>

		<Card.Root>
			<Card.Header>
				<h2 class="text-lg font-semibold text-card-foreground">User activity (7d)</h2>
			</Card.Header>
			<Card.Content>
				<div class="grid grid-cols-3 gap-4">
					<div>
						<div class="text-2xl font-bold text-card-foreground">{formatNumber(stats.activity_7d.active_users)}</div>
						<div class="text-xs text-muted-foreground">Active users</div>
					</div>
					<div>
						<div class="text-2xl font-bold text-card-foreground">{formatNumber(stats.activity_7d.new_ratings)}</div>
						<div class="text-xs text-muted-foreground">New ratings</div>
					</div>
					<div>
						<div class="text-2xl font-bold text-card-foreground">{formatNumber(stats.activity_7d.scrapes_submitted)}</div>
						<div class="text-xs text-muted-foreground">Scrapes submitted</div>
					</div>
				</div>
			</Card.Content>
		</Card.Root>
	{/if}
</div>
