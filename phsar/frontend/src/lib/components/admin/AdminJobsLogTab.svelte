<script lang="ts">
	import { onMount } from 'svelte';
	import { goto } from '$app/navigation';
	import { api, ApiError } from '$lib/api';
	import { Button } from '$lib/components/ui/button';
	import * as Card from '$lib/components/ui/card';
	import * as Select from '$lib/components/ui/select';
	import { Badge } from '$lib/components/ui/badge';
	import { Label } from '$lib/components/ui/label';
	import { ChevronRight } from 'lucide-svelte';
	import { JOB_KIND_LABELS, PARENTING_KINDS, formatJobDuration, formatJobKind, formatShortDateTime } from '$lib/utils/formatString';
	import { STATUS_BADGE } from '$lib/utils/jobBadges';
	import type { AdminJobResponse, AdminJobsPage, JobKind, JobStatus } from '$lib/types/api';

	const PAGE_SIZE = 50;

	const KIND_OPTIONS: { value: '' | JobKind; label: string }[] = [
		{ value: '', label: 'All kinds' },
		...(Object.keys(JOB_KIND_LABELS) as JobKind[]).map((k) => ({ value: k, label: formatJobKind(k) })),
	];

	const STATUS_OPTIONS: { value: '' | JobStatus; label: string }[] = [
		{ value: '', label: 'All statuses' },
		{ value: 'queued', label: 'Queued' },
		{ value: 'running', label: 'Running' },
		{ value: 'succeeded', label: 'Succeeded' },
		{ value: 'failed', label: 'Failed' },
	];

	let kindFilter = $state<'' | JobKind>('');
	let statusFilter = $state<'' | JobStatus>('');
	let offset = $state(0);

	let page = $state<AdminJobsPage | null>(null);
	let loading = $state(true);
	let error = $state('');
	// Monotonic request id — a rapid filter-then-page click would let the
	// older response overwrite the newer one without this guard.
	let loadRequestId = 0;

	let totalPages = $derived(page ? Math.max(1, Math.ceil(page.total / PAGE_SIZE)) : 1);
	let currentPage = $derived(Math.floor(offset / PAGE_SIZE) + 1);

	async function load() {
		const thisRequest = ++loadRequestId;
		loading = true;
		error = '';
		try {
			const params = new URLSearchParams({
				limit: String(PAGE_SIZE),
				offset: String(offset),
			});
			if (kindFilter) params.set('kind', kindFilter);
			if (statusFilter) params.set('status', statusFilter);
			const result = await api.get<AdminJobsPage>(`/admin/jobs?${params.toString()}`);
			if (thisRequest !== loadRequestId) return;
			page = result;
		} catch (err) {
			if (thisRequest !== loadRequestId) return;
			error = err instanceof ApiError ? err.detail : 'Failed to load jobs';
		} finally {
			if (thisRequest === loadRequestId) loading = false;
		}
	}

	onMount(load);

	// Filter changes always reset to page 1 — keeping a stale offset on a
	// narrower filter would strand the admin past the result tail.
	function setKindFilter(v: string) {
		kindFilter = v as '' | JobKind;
		offset = 0;
		void load();
	}
	function setStatusFilter(v: string) {
		statusFilter = v as '' | JobStatus;
		offset = 0;
		void load();
	}
	function gotoPage(newOffset: number) {
		offset = newOffset;
		void load();
	}

	// Backend accepts ?parent_uuid= for any kind, so PARENTING_KINDS is
	// the frontend's visual guard — adding a future parent-stamping kind
	// only needs the constant in formatString.ts. Carry the response total
	// alongside the rows so the renderer can surface truncation honestly
	// if a sweep ever exceeds CHILDREN_LIMIT.
	const CHILDREN_LIMIT = 500;
	type ChildrenState = { items: AdminJobResponse[]; total: number } | 'loading' | { error: string };
	let childrenByParent = $state<Record<string, ChildrenState>>({});
	let expandedUuids = $state<Set<string>>(new Set());

	function isLoaded(s: ChildrenState | undefined): s is { items: AdminJobResponse[]; total: number } {
		return typeof s === 'object' && s !== null && 'items' in s;
	}

	async function toggleExpand(parentUuid: string) {
		const next = new Set(expandedUuids);
		if (next.has(parentUuid)) {
			next.delete(parentUuid);
			expandedUuids = next;
			return;
		}
		next.add(parentUuid);
		expandedUuids = next;
		if (isLoaded(childrenByParent[parentUuid])) return;
		childrenByParent = { ...childrenByParent, [parentUuid]: 'loading' };
		try {
			const resp = await api.get<AdminJobsPage>(
				`/admin/jobs?parent_uuid=${parentUuid}&limit=${CHILDREN_LIMIT}`,
			);
			childrenByParent = {
				...childrenByParent,
				[parentUuid]: { items: resp.items, total: resp.total },
			};
		} catch (err) {
			childrenByParent = {
				...childrenByParent,
				[parentUuid]: { error: err instanceof ApiError ? err.detail : 'Failed to load children' },
			};
		}
	}

	// `now` ticks while any row is running so the Duration column updates
	// in place without a re-fetch. Quiet when nothing is running so we
	// don't burn render cycles on a stable Jobs Log view.
	let now = $state(Date.now());
	// Short-circuit: page items first (always ≤ PAGE_SIZE rows). Only
	// walk every loaded child set when no top-level row is running —
	// otherwise we'd re-scan hundreds of children per second tick.
	let hasRunning = $derived.by(() => {
		if ((page?.items ?? []).some((r) => r.status === 'running')) return true;
		return Object.values(childrenByParent).some(
			(s) => isLoaded(s) && s.items.some((r) => r.status === 'running'),
		);
	});
	$effect(() => {
		if (!hasRunning) return;
		const id = setInterval(() => (now = Date.now()), 1000);
		return () => clearInterval(id);
	});

	function rowDuration(row: AdminJobResponse): string {
		return formatJobDuration(row.started_at, row.finished_at, now);
	}

	// A row is clickable when its detail page actually has more to show
	// than the row itself — today only update_sweep ≥ v2 (per-media diff
	// inspector). v1 sweep rows would land on a "predates the rework"
	// notice, so the click affordance stays off for them.
	function isClickableJob(row: AdminJobResponse): boolean {
		return row.kind === 'update_sweep' && row.version >= 2;
	}

	// v3+ sweeps expose a deduplicated list of MAL genre tags the seeder
	// doesn't know yet. Surface them at the row level so the admin can
	// spot which sweeps need a seeder update without drilling in.
	function unknownGenreTags(row: AdminJobResponse): string[] {
		const tags = row.result_summary?.unknown_genre_tags;
		return Array.isArray(tags) ? (tags as string[]) : [];
	}

	function clickableNavProps(uuid: string) {
		const go = () => void goto(`/admin/jobs/${uuid}`);
		return {
			role: 'link',
			tabindex: 0,
			onclick: go,
			onkeydown: (e: KeyboardEvent) => { if (e.key === 'Enter') go(); },
		};
	}

	// JSONB lookups land as `unknown` per the JobResultSummary index signature;
	// this narrows safely so the formatter doesn't crash on legacy/malformed rows.
	const num = (v: unknown): number => (typeof v === 'number' ? v : 0);

	function payloadSummary(row: AdminJobsPage['items'][number]): string {
		if (row.kind === 'user_scrape') {
			const q = typeof row.payload?.query === 'string' ? `"${row.payload.query}"` : '';
			if (row.status === 'succeeded' && row.result_summary) {
				const a = num(row.result_summary.anime_count);
				const m = num(row.result_summary.media_count);
				return `+${a} anime · +${m} media${q ? ` (${q})` : ''}`;
			}
			return q;
		}
		if (row.kind === 'backup' || row.kind === 'restore') {
			const filename = row.result_summary?.filename;
			return typeof filename === 'string' ? filename : '';
		}
		if (row.kind === 'update_sweep' && row.status === 'succeeded' && row.result_summary) {
			// v2 (post-v0.14.5) nests aggregate counts under `counters` and
			// carries per-media diffs the detail page renders. v1 rows pre-
			// date the rework — fall back to the flat shape.
			if (row.version >= 2) {
				const c = (row.result_summary.counters ?? {}) as Record<string, unknown>;
				const refreshed = num(c.anime_refreshed);
				const dynAnime = num(c.anime_with_dynamic_changes);
				const staticMedia = num(c.media_with_static_changes);
				const umbrella = num(c.umbrella_reclassed);
				const probeAttached = num(c.probe_attached_anime_count);
				const parts = [`${refreshed} touched`];
				if (dynAnime > 0) parts.push(`${dynAnime} anime w/ dynamic`);
				if (staticMedia > 0) parts.push(`${staticMedia} media w/ static`);
				if (umbrella > 0) parts.push(`${umbrella} umbrella`);
				if (probeAttached > 0) parts.push(`${probeAttached} new attached`);
				return parts.join(' · ');
			}
			const refreshed = num(row.result_summary.anime_refreshed);
			const changed = num(row.result_summary.anime_changed);
			const metadataChanged = num(row.result_summary.metadata_changed_media);
			const probeAttached = num(row.result_summary.probe_attached_anime_count);
			const parts = [`refreshed ${refreshed} anime`, `${changed} changed`];
			if (metadataChanged > 0) parts.push(`${metadataChanged} media updated`);
			if (probeAttached > 0) parts.push(`${probeAttached} new attached`);
			return parts.join(' · ');
		}
		if (row.kind === 'seasonal_sweep' && row.status === 'succeeded' && row.result_summary) {
			const entries = num(row.result_summary.season_entries);
			const enqueued = num(row.result_summary.new_entries_enqueued);
			const dedup = num(row.result_summary.dedup_skipped);
			return `${entries} season entries · ${enqueued} new scrapes enqueued · ${dedup} already known`;
		}
		return '';
	}
</script>

<Card.Root>
	<Card.Header>
		<h2 class="text-lg font-semibold text-card-foreground">Jobs log</h2>
	</Card.Header>
	<Card.Content class="space-y-4">
		<div class="flex flex-wrap items-end gap-3">
			<div class="space-y-1">
				<Label>Kind</Label>
				<Select.Root type="single" value={kindFilter} onValueChange={(v) => { if (v !== undefined) setKindFilter(v); }}>
					<Select.Trigger class="w-44">
						{KIND_OPTIONS.find(o => o.value === kindFilter)?.label}
					</Select.Trigger>
					<Select.Content>
						{#each KIND_OPTIONS as opt}
							<Select.Item value={opt.value}>{opt.label}</Select.Item>
						{/each}
					</Select.Content>
				</Select.Root>
			</div>
			<div class="space-y-1">
				<Label>Status</Label>
				<Select.Root type="single" value={statusFilter} onValueChange={(v) => { if (v !== undefined) setStatusFilter(v); }}>
					<Select.Trigger class="w-40">
						{STATUS_OPTIONS.find(o => o.value === statusFilter)?.label}
					</Select.Trigger>
					<Select.Content>
						{#each STATUS_OPTIONS as opt}
							<Select.Item value={opt.value}>{opt.label}</Select.Item>
						{/each}
					</Select.Content>
				</Select.Root>
			</div>
		</div>

		{#if error}
			<p class="text-destructive text-sm">{error}</p>
		{:else if loading && !page}
			<p class="text-muted-foreground text-sm">Loading jobs…</p>
		{:else if page}
			{#if page.items.length === 0}
				<p class="text-muted-foreground text-sm">No jobs match the current filters.</p>
			{:else}
				<div class="overflow-x-auto">
					<table class="w-full text-sm">
						<thead>
							<tr class="text-left text-xs uppercase tracking-wide text-muted-foreground border-b border-border">
								<th class="py-2 pr-2 font-medium w-6"></th>
								<th class="py-2 pr-3 font-medium">Created</th>
								<th class="py-2 pr-3 font-medium">Kind</th>
								<th class="py-2 pr-3 font-medium">Status</th>
								<th class="py-2 pr-3 font-medium">Duration</th>
								<th class="py-2 pr-3 font-medium">User</th>
								<th class="py-2 pr-3 font-medium">Detail</th>
							</tr>
						</thead>
						<tbody>
							{#each page.items as row (row.uuid)}
								{@const expanded = expandedUuids.has(row.uuid)}
								{@const expandable = PARENTING_KINDS.has(row.kind)}
								{@const clickable = isClickableJob(row)}
								{@const unknownTags = unknownGenreTags(row)}
								<tr
									class="border-b border-border/50 align-top {clickable ? 'cursor-pointer hover:bg-muted/20 transition-colors' : ''} {unknownTags.length > 0 ? 'bg-amber-500/15 border-l-2 border-l-amber-400' : ''}"
									{...(clickable ? clickableNavProps(row.uuid) : {})}
								>
									<td class="py-2 pr-2 w-6">
										{#if expandable}
											<button
												type="button"
												class="text-muted-foreground hover:text-card-foreground transition"
												aria-label={expanded ? 'Collapse children' : 'Expand children'}
												onclick={(e) => { e.stopPropagation(); void toggleExpand(row.uuid); }}
											>
												<ChevronRight class="size-4 transition-transform {expanded ? 'rotate-90' : ''}" />
											</button>
										{/if}
									</td>
									<td class="py-2 pr-3 text-card-foreground whitespace-nowrap">{formatShortDateTime(row.created_at)}</td>
									<td class="py-2 pr-3">
										<Badge variant="secondary" class="text-[11px]">{row.kind}</Badge>
									</td>
									<td class="py-2 pr-3">
										<Badge class="text-[11px] {STATUS_BADGE[row.status]}">{row.status}</Badge>
									</td>
									<td class="py-2 pr-3 text-card-foreground/80 whitespace-nowrap tabular-nums">
										{rowDuration(row)}
									</td>
									<td class="py-2 pr-3 text-card-foreground">
										{row.requested_by_username ?? 'system'}
									</td>
									<td class="py-2 pr-3 text-card-foreground/80 max-w-md">
										{#if row.status === 'failed' && row.error_message}
											<span class="text-destructive">{row.error_message}</span>
										{:else}
											<div class="truncate">{payloadSummary(row)}</div>
											{#if unknownTags.length > 0}
												<div class="mt-1 text-xs font-medium text-amber-300">
													⚠ New genre {unknownTags.length === 1 ? 'tag needs' : 'tags need'} seeding:
													<span class="font-mono">{unknownTags.join(', ')}</span>
												</div>
											{/if}
										{/if}
									</td>
								</tr>
								{#if expanded}
									{@const childState = childrenByParent[row.uuid]}
									{#if childState === 'loading'}
										<tr class="border-b border-border/30 bg-muted/10">
											<td></td>
											<td class="py-2 pr-3 text-xs text-muted-foreground italic" colspan="6">Loading children…</td>
										</tr>
									{:else if childState && !isLoaded(childState)}
										<tr class="border-b border-border/30 bg-muted/10">
											<td></td>
											<td class="py-2 pr-3 text-xs text-destructive" colspan="6">{childState.error}</td>
										</tr>
									{:else if isLoaded(childState) && childState.items.length === 0}
										<tr class="border-b border-border/30 bg-muted/10">
											<td></td>
											<td class="py-2 pr-3 text-xs text-muted-foreground italic" colspan="6">No child jobs were enqueued.</td>
										</tr>
									{:else if isLoaded(childState)}
										{#each childState.items as child (child.uuid)}
											{@const childClickable = isClickableJob(child)}
											<tr
												class="border-b border-border/30 bg-muted/10 align-top {childClickable ? 'cursor-pointer hover:bg-muted/30 transition-colors' : ''}"
												{...(childClickable ? clickableNavProps(child.uuid) : {})}
											>
												<td class="py-1.5 pr-2 border-l-2 border-primary/40"></td>
												<td class="py-1.5 pr-3 text-card-foreground whitespace-nowrap text-xs">{formatShortDateTime(child.created_at)}</td>
												<td class="py-1.5 pr-3">
													<Badge variant="secondary" class="text-[10px]">{child.kind}</Badge>
												</td>
												<td class="py-1.5 pr-3">
													<Badge class="text-[10px] {STATUS_BADGE[child.status]}">{child.status}</Badge>
												</td>
												<td class="py-1.5 pr-3 text-card-foreground/80 whitespace-nowrap tabular-nums text-xs">
													{rowDuration(child)}
												</td>
												<td class="py-1.5 pr-3 text-card-foreground text-xs">
													{child.requested_by_username ?? 'system'}
												</td>
												<td class="py-1.5 pr-3 text-card-foreground/80 max-w-md truncate text-xs">
													{#if child.status === 'failed' && child.error_message}
														<span class="text-destructive">{child.error_message}</span>
													{:else}
														{payloadSummary(child)}
													{/if}
												</td>
											</tr>
										{/each}
										{#if childState.total > childState.items.length}
											<tr class="border-b border-border/30 bg-muted/10">
												<td class="py-1.5 pr-2 border-l-2 border-primary/40"></td>
												<td class="py-1.5 pr-3 text-xs text-amber-400 italic" colspan="6">
													Showing {childState.items.length} of {childState.total} children — the rest are older than the {CHILDREN_LIMIT}-row cap.
												</td>
											</tr>
										{/if}
									{/if}
								{/if}
							{/each}
						</tbody>
					</table>
				</div>
			{/if}

			<div class="flex items-center justify-between text-sm text-muted-foreground">
				<span>
					{page.total === 0 ? '0' : `${offset + 1}–${Math.min(offset + page.items.length, page.total)}`} of {page.total}
				</span>
				<div class="flex items-center gap-2">
					<Button
						variant="secondary"
						size="sm"
						disabled={offset === 0 || loading}
						onclick={() => gotoPage(Math.max(0, offset - PAGE_SIZE))}
					>
						Prev
					</Button>
					<span>Page {currentPage} of {totalPages}</span>
					<Button
						variant="secondary"
						size="sm"
						disabled={currentPage >= totalPages || loading}
						onclick={() => gotoPage(offset + PAGE_SIZE)}
					>
						Next
					</Button>
				</div>
			</div>
		{/if}
	</Card.Content>
</Card.Root>
