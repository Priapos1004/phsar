<script lang="ts">
	import { onMount } from 'svelte';
	import { api, ApiError } from '$lib/api';
	import { Button } from '$lib/components/ui/button';
	import * as Card from '$lib/components/ui/card';
	import * as Select from '$lib/components/ui/select';
	import { Badge } from '$lib/components/ui/badge';
	import { Label } from '$lib/components/ui/label';
	import { JOB_KIND_LABELS, formatJobKind, formatShortDateTime } from '$lib/utils/formatString';
	import type { AdminJobsPage, JobKind, JobStatus } from '$lib/types/api';

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

	const STATUS_BADGE: Record<JobStatus, string> = {
		queued: 'bg-muted text-muted-foreground',
		running: 'bg-primary/15 text-primary',
		succeeded: 'bg-emerald-500/15 text-emerald-400',
		failed: 'bg-destructive/15 text-destructive',
	};

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
								<th class="py-2 pr-3 font-medium">Created</th>
								<th class="py-2 pr-3 font-medium">Kind</th>
								<th class="py-2 pr-3 font-medium">Status</th>
								<th class="py-2 pr-3 font-medium">User</th>
								<th class="py-2 pr-3 font-medium">Detail</th>
							</tr>
						</thead>
						<tbody>
							{#each page.items as row (row.uuid)}
								<tr class="border-b border-border/50 align-top">
									<td class="py-2 pr-3 text-card-foreground whitespace-nowrap">{formatShortDateTime(row.created_at)}</td>
									<td class="py-2 pr-3">
										<Badge variant="secondary" class="text-[11px]">{row.kind}</Badge>
									</td>
									<td class="py-2 pr-3">
										<Badge class="text-[11px] {STATUS_BADGE[row.status]}">{row.status}</Badge>
									</td>
									<td class="py-2 pr-3 text-card-foreground">
										{row.requested_by_username ?? 'system'}
									</td>
									<td class="py-2 pr-3 text-card-foreground/80 max-w-md truncate">
										{#if row.status === 'failed' && row.error_message}
											<span class="text-destructive">{row.error_message}</span>
										{:else}
											{payloadSummary(row)}
										{/if}
									</td>
								</tr>
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
