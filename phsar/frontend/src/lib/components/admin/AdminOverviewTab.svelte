<script lang="ts">
	import { onMount } from 'svelte';
	import { api, ApiError } from '$lib/api';
	import * as Card from '$lib/components/ui/card';
	import SweepTiersCard from '$lib/components/admin/SweepTiersCard.svelte';
	import Tooltip from '$lib/components/Tooltip.svelte';
	import { formatJobKind, formatNumber, percentOf } from '$lib/utils/formatString';
	import { byWindow } from '$lib/utils/jobHealth';
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

	const JOB_HEALTH_COLUMNS = ['Ok', 'Failed', 'Rate'];
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
			<Card.Content>
				<!-- One grid for the whole card, dividers spanning it, so the number
				     columns align ACROSS the window groups and not just within one.
				     That alignment is what makes the Failed column scannable: a dimmed
				     zero against a `destructive` non-zero, at a fixed x. -->
				<div class="grid grid-cols-[minmax(0,1fr)_3rem_3.5rem_3.5rem] items-center gap-x-3 gap-y-2 text-sm">
					<!-- The heading takes the header row's first column: it labels
					     these columns. -->
					<h2 class="text-lg font-semibold text-card-foreground">Job health</h2>
					{#each JOB_HEALTH_COLUMNS as heading (heading)}
						<div class="self-end pb-1 text-right text-[10px] uppercase tracking-wider text-muted-foreground">
							{heading}
						</div>
					{/each}

					{#each byWindow(stats.jobs.by_kind) as group (group.days)}
						<!-- The window is a property of the group, so it renders as a
						     centred rule spanning the grid: flush-left above the job
						     names it reads as another row. -->
						<div class="col-span-4 flex items-center gap-3 pt-1">
							<div class="h-px flex-1 bg-border"></div>
							<span class="text-[10px] uppercase tracking-wider text-muted-foreground">
								Last {group.days} days
							</span>
							<div class="h-px flex-1 bg-border"></div>
						</div>
						{#each group.rows as row (row.kind)}
							{@const total = row.succeeded + row.failed}
							{@const rate = total > 0 ? Math.round(percentOf(row.succeeded, total)) : null}
							<span class="truncate text-card-foreground">{formatJobKind(row.kind)}</span>
							<span class="text-right tabular-nums {row.succeeded > 0 ? 'text-muted-foreground' : 'text-muted-foreground/40'}">
								{row.succeeded}
							</span>
							<span
								class="text-right tabular-nums {row.failed > 0 ? 'font-medium text-destructive' : 'text-muted-foreground/40'}"
								title={row.retryable_failed > 0 ? `${row.retryable_failed} of these can still retry` : undefined}
							>
								{row.failed}
							</span>
							<span
								class="text-right font-semibold tabular-nums {rate === null
									? 'text-muted-foreground/40'
									: rate >= 90
										? 'text-emerald-400'
										: rate >= 75
											? 'text-amber-400'
											: 'text-destructive'}"
							>
								{rate === null ? '—' : `${rate}%`}
							</span>
						{/each}
					{/each}
				</div>
			</Card.Content>
		</Card.Root>

		<SweepTiersCard animeTiers={stats.sweep_tiers} mediaTiers={stats.media_sweep_tiers} />

		<Card.Root>
			<Card.Header>
				<h2 class="text-lg font-semibold text-card-foreground">Watchlists</h2>
			</Card.Header>
			<Card.Content>
				<!-- All-users aggregate (no leaderboard). Grid pairs each total above its
				     related figure: media/avg-media, anime/users, lists/avg-lists. The two
				     averages use different denominators on purpose: avg media is "per active
				     watchlist user" (users with an entry); avg lists is ADOPTION, over the whole
				     eligible (non-guest) base so users who made no list count against it. -->
				<div class="grid grid-cols-3 gap-4">
					<div>
						<div class="text-2xl font-bold text-card-foreground">{formatNumber(stats.watchlist.total_entries)}</div>
						<div class="text-xs text-muted-foreground">Media on watchlists</div>
					</div>
					<div>
						<div class="text-2xl font-bold text-card-foreground">{formatNumber(stats.watchlist.total_anime)}</div>
						<div class="text-xs text-muted-foreground">Distinct anime</div>
					</div>
					<div>
						<div class="text-2xl font-bold text-card-foreground">{formatNumber(stats.watchlist.total_custom_lists)}</div>
						<Tooltip text="User-created lists across all accounts. Excludes the default &quot;Watchlist&quot; list every account starts with.">
							<span class="text-xs text-muted-foreground cursor-help border-b border-dotted border-muted-foreground/40">Custom lists</span>
						</Tooltip>
					</div>
					<div>
						<div class="text-2xl font-bold text-primary">{stats.watchlist.avg_entries_per_user}</div>
						<Tooltip text="Media per active watchlist user (accounts with at least one saved item).">
							<span class="text-xs text-muted-foreground cursor-help border-b border-dotted border-muted-foreground/40">Avg media / user</span>
						</Tooltip>
					</div>
					<div>
						<div class="text-2xl font-bold text-card-foreground">{formatNumber(stats.watchlist.users_with_entries)}</div>
						<Tooltip text="Accounts with at least one saved item — not just the default list every account starts with.">
							<span class="text-xs text-muted-foreground cursor-help border-b border-dotted border-muted-foreground/40">Users with a watchlist</span>
						</Tooltip>
					</div>
					<div>
						<div class="text-2xl font-bold text-primary">{stats.watchlist.avg_custom_lists_per_user}</div>
						<Tooltip text="Custom lists per account, across every non-guest user — an adoption measure that counts users who made none. Excludes the default &quot;Watchlist&quot; list.">
							<span class="text-xs text-muted-foreground cursor-help border-b border-dotted border-muted-foreground/40">Avg lists / user</span>
						</Tooltip>
					</div>
				</div>
			</Card.Content>
		</Card.Root>

		<Card.Root>
			<Card.Header>
				<h2 class="text-lg font-semibold text-card-foreground">User activity (7d)</h2>
			</Card.Header>
			<Card.Content>
				<div class="grid grid-cols-2 sm:grid-cols-4 gap-4">
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
					<div>
						<div class="text-2xl font-bold text-card-foreground">{formatNumber(stats.activity_7d.watchlist_modifications)}</div>
						<div class="text-xs text-muted-foreground">Watchlist edits</div>
					</div>
				</div>
			</Card.Content>
		</Card.Root>
	{/if}
</div>
