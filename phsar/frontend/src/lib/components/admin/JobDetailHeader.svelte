<script lang="ts">
	import { Badge } from '$lib/components/ui/badge';
	import * as Card from '$lib/components/ui/card';
	import { ArrowLeft, ExternalLink } from 'lucide-svelte';
	import { formatJobDuration, formatJobKind, formatShortDateTime } from '$lib/utils/formatString';
	import { STATUS_BADGE } from '$lib/utils/jobBadges';
	import type { AdminJobResponse } from '$lib/types/api';

	interface Props {
		job: AdminJobResponse;
	}
	let { job }: Props = $props();

	// Live ticker only while the job is running — finished/queued rows
	// don't need a clock, and a stable detail page shouldn't churn its
	// reactivity tree once a second.
	let now = $state(Date.now());
	$effect(() => {
		if (job.status !== 'running') return;
		const id = setInterval(() => (now = Date.now()), 1000);
		return () => clearInterval(id);
	});

	let duration = $derived(formatJobDuration(job.started_at, job.finished_at, now));
	let headerTitle = $derived(`${formatJobKind(job.kind)} · ${formatShortDateTime(job.created_at)}`);
</script>

<Card.Root>
	<Card.Header class="space-y-2">
		<div class="flex items-center justify-between gap-4 flex-wrap">
			<div class="flex items-center gap-2">
				<a
					href="/admin?tab=jobs"
					class="inline-flex items-center gap-1 text-sm text-muted-foreground hover:text-card-foreground transition-colors"
				>
					<ArrowLeft class="size-4" />
					Jobs Log
				</a>
			</div>
			<div class="flex items-center gap-2">
				<Badge variant="secondary">{job.kind}</Badge>
				<Badge class={STATUS_BADGE[job.status]}>{job.status}</Badge>
				<Badge variant="secondary" class="text-[10px] uppercase tracking-wide">v{job.version}</Badge>
			</div>
		</div>
		<div class="space-y-1">
			<h1 class="text-xl font-semibold text-card-foreground">{headerTitle}</h1>
			<p class="text-xs text-muted-foreground break-all font-mono">{job.uuid}</p>
		</div>
	</Card.Header>
	<Card.Content>
		<dl class="grid grid-cols-2 md:grid-cols-4 gap-y-3 gap-x-6 text-sm">
			<div>
				<dt class="text-xs uppercase tracking-wide text-muted-foreground">Created</dt>
				<dd class="text-card-foreground">{formatShortDateTime(job.created_at)}</dd>
			</div>
			<div>
				<dt class="text-xs uppercase tracking-wide text-muted-foreground">Started</dt>
				<dd class="text-card-foreground">{job.started_at ? formatShortDateTime(job.started_at) : '—'}</dd>
			</div>
			<div>
				<dt class="text-xs uppercase tracking-wide text-muted-foreground">Finished</dt>
				<dd class="text-card-foreground">{job.finished_at ? formatShortDateTime(job.finished_at) : '—'}</dd>
			</div>
			<div>
				<dt class="text-xs uppercase tracking-wide text-muted-foreground">Duration</dt>
				<dd class="text-card-foreground tabular-nums">{duration}</dd>
			</div>
			<div>
				<dt class="text-xs uppercase tracking-wide text-muted-foreground">Requested by</dt>
				<dd class="text-card-foreground">{job.requested_by_username ?? 'system'}</dd>
			</div>
			{#if job.parent_job_uuid}
				<div class="col-span-2 md:col-span-3">
					<dt class="text-xs uppercase tracking-wide text-muted-foreground">Parent job</dt>
					<dd>
						<a
							href={`/admin/jobs/${job.parent_job_uuid}`}
							class="inline-flex items-center gap-1 text-primary hover:underline break-all"
						>
							{job.parent_job_uuid}
							<ExternalLink class="size-3.5" />
						</a>
					</dd>
				</div>
			{/if}
		</dl>
		{#if job.status === 'failed' && job.error_message}
			<p class="mt-4 rounded-md border border-destructive/30 bg-destructive/10 p-3 text-sm text-destructive">
				{job.error_message}
			</p>
		{/if}
	</Card.Content>
</Card.Root>
