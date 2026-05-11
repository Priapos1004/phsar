<script lang="ts">
	import { onDestroy } from 'svelte';
	import { Bell, RefreshCw, CheckCircle2, XCircle, Loader2 } from 'lucide-svelte';
	import * as DropdownMenu from '$lib/components/ui/dropdown-menu';
	import { api, ApiError } from '$lib/api';
	import { bumpLibrarySaved, jobsRefresh, onBump } from '$lib/stores/jobs';
	import { BELL_LOGIN_KEY, BELL_SEEN_KEY } from '$lib/stores/bell-session';
	import type { Job } from '$lib/types/api';

	const ACTIVE_POLL_MS = 4000;
	const IDLE_POLL_MS = 30000;
	// Cap the dropdown so a noisy session (max 4 active per JOBS_PER_USER_LIMIT
	// + recent finishes) stays readable. Older entries live on /library/add.
	const MAX_VISIBLE = 5;

	// Captured once per tab/session. The bell only surfaces jobs created
	// after this point — completed jobs from prior sessions live on the
	// /library/add "recent additions" panel, not here.
	function readOrInitSessionTimestamp(key: string): string {
		if (typeof sessionStorage === 'undefined') return new Date().toISOString();
		const existing = sessionStorage.getItem(key);
		if (existing) return existing;
		const now = new Date().toISOString();
		sessionStorage.setItem(key, now);
		return now;
	}

	function loadSeen(): Set<string> {
		if (typeof sessionStorage === 'undefined') return new Set();
		const raw = sessionStorage.getItem(BELL_SEEN_KEY);
		if (!raw) return new Set();
		try {
			const parsed = JSON.parse(raw);
			return Array.isArray(parsed) ? new Set(parsed) : new Set();
		} catch {
			return new Set();
		}
	}

	const sessionStart = readOrInitSessionTimestamp(BELL_LOGIN_KEY);

	let jobs = $state<Job[]>([]);
	// UUID-based "seen" tracking: storing finished_at would couple "seen"
	// detection to client-server clock alignment. UUIDs are stable.
	let seenUuids = $state(loadSeen());
	let dropdownOpen = $state(false);
	let pollTimer: ReturnType<typeof setTimeout> | null = null;
	let stopped = false;
	// UUIDs of user_scrape jobs we've already announced to /library/add via
	// bumpLibrarySaved — prevents the bell from re-triggering a refresh on
	// every poll while a succeeded job is still in the response window.
	let announcedSavedUuids = new Set<string>();
	// Block re-clicks while a retry is in flight so each click maps to one job.
	let retryingUuid = $state<string | null>(null);

	let visibleJobs = $derived(jobs.filter((j) => j.created_at >= sessionStart));
	// Cap the dropdown rendering. Badge math still uses the full visibleJobs
	// list so a user with 6 active scrapes sees an honest count even though
	// only 5 rows render. Older entries are reachable on /library/add.
	let displayedJobs = $derived(visibleJobs.slice(0, MAX_VISIBLE));
	let activeJobs = $derived(
		visibleJobs.filter((j) => j.status === 'queued' || j.status === 'running'),
	);
	let unseenFinished = $derived(
		visibleJobs.filter(
			(j) =>
				(j.status === 'succeeded' || j.status === 'failed') && !seenUuids.has(j.uuid),
		),
	);
	let badgeCount = $derived(activeJobs.length + unseenFinished.length);
	let hiddenCount = $derived(Math.max(0, visibleJobs.length - MAX_VISIBLE));
	let pollDelay = $derived(activeJobs.length > 0 ? ACTIVE_POLL_MS : IDLE_POLL_MS);

	async function fetchJobs() {
		try {
			const fresh = await api.get<Job[]>('/jobs/mine');
			jobs = fresh;
			// Announce any newly-succeeded user_scrape jobs so /library/add
			// refreshes its recent-additions panel without a page reload.
			let anyNew = false;
			for (const job of fresh) {
				if (
					job.kind === 'user_scrape' &&
					job.status === 'succeeded' &&
					job.created_at >= sessionStart &&
					!announcedSavedUuids.has(job.uuid)
				) {
					announcedSavedUuids.add(job.uuid);
					anyNew = true;
				}
			}
			if (anyNew) bumpLibrarySaved();
		} catch (err) {
			// 401 means logged out — the global ApiError handler in api.ts will
			// redirect on maintenance; for plain auth failures we just stop
			// polling silently.
			if (err instanceof ApiError && err.status === 401) {
				stopPolling();
				return;
			}
			console.error('JobBell poll failed:', err);
		}
	}

	function schedule() {
		if (stopped) return;
		clearTimer();
		pollTimer = setTimeout(async () => {
			await fetchJobs();
			schedule();
		}, pollDelay);
	}

	function clearTimer() {
		if (pollTimer !== null) {
			clearTimeout(pollTimer);
			pollTimer = null;
		}
	}

	function stopPolling() {
		stopped = true;
		clearTimer();
	}

	$effect(() => {
		// Kick off the first fetch immediately on mount; subsequent ticks
		// follow the active/idle cadence.
		void fetchJobs().then(schedule);
		return stopPolling;
	});

	// /library/add bumps jobsRefresh after a successful POST so the bell
	// refetches /jobs/mine in tens of milliseconds, not waiting for the 30s
	// idle poll. onBump skips the initial synchronous fire so this doesn't
	// double-fetch with the mount-time fetchJobs above.
	$effect(() => onBump(jobsRefresh, () => void fetchJobs()));

	$effect(() => {
		// Mark all currently-finished jobs as seen the moment the dropdown opens.
		if (!dropdownOpen) return;
		const updated = new Set(seenUuids);
		let changed = false;
		for (const job of visibleJobs) {
			if ((job.status === 'succeeded' || job.status === 'failed') && !updated.has(job.uuid)) {
				updated.add(job.uuid);
				changed = true;
			}
		}
		if (!changed) return;
		seenUuids = updated;
		if (typeof sessionStorage !== 'undefined') {
			sessionStorage.setItem(BELL_SEEN_KEY, JSON.stringify([...updated]));
		}
	});

	function statusIcon(job: Job) {
		if (job.status === 'queued') return Bell;
		if (job.status === 'running') return Loader2;
		if (job.status === 'succeeded') return CheckCircle2;
		return XCircle;
	}

	function statusColor(job: Job): string {
		if (job.status === 'succeeded') return 'text-green-500';
		if (job.status === 'failed') return 'text-destructive';
		if (job.status === 'running') return 'text-primary';
		return 'text-muted-foreground';
	}

	function progressPercent(job: Job): number | null {
		if (job.items_total === null || job.items_total === 0) return null;
		return Math.min(100, Math.round((job.items_done / job.items_total) * 100));
	}

	function describeJob(job: Job): string {
		const query = typeof job.payload?.query === 'string' ? job.payload.query : null;
		if (query) return `Add: "${query}"`;
		return job.kind.replace('_', ' ');
	}

	function isRetryable(job: Job): boolean {
		// Default true — only the dispatcher's PermanentPhsarError path stamps
		// retryable=false. Missing field (older rows, non-job errors) → still
		// retryable so we don't break the historical bell behavior.
		const flag = job.result_summary?.retryable;
		return flag !== false;
	}

	function describeError(job: Job): string {
		// Backend stamps result_summary.error_category for failure modes that
		// have a clear user-facing message. Anything not categorized falls
		// through to the raw error_message — custom domain errors
		// (AnimeNotFoundError, MainMediaNotFoundError, MalIdAlreadyExistsError)
		// already carry their own copy so the raw text is already friendly.
		const category = job.result_summary?.error_category;
		if (category === 'upstream_outage') {
			return 'Anime database is temporarily unavailable. Please retry in a few minutes.';
		}
		return job.error_message ?? 'Failed';
	}

	async function retryJob(job: Job, event: MouseEvent) {
		event.stopPropagation();
		if (retryingUuid !== null) return;
		const query = typeof job.payload?.query === 'string' ? job.payload.query : null;
		if (!query) return;
		retryingUuid = job.uuid;
		try {
			await api.post('/jobs/scrape', { query });
			await fetchJobs();
		} catch (err) {
			console.error('Retry failed:', err);
		} finally {
			retryingUuid = null;
		}
	}

	onDestroy(stopPolling);
</script>

<DropdownMenu.Root bind:open={dropdownOpen}>
	<DropdownMenu.Trigger
		class="relative w-9 h-9 rounded-full hover:bg-white/10 flex items-center justify-center transition"
		aria-label="Background jobs"
	>
		<Bell class="w-5 h-5 text-white" />
		{#if badgeCount > 0}
			<span
				class="absolute -top-0.5 -right-0.5 min-w-4 h-4 px-1 rounded-full bg-primary text-primary-foreground text-[10px] font-bold flex items-center justify-center"
			>
				{badgeCount}
			</span>
		{/if}
	</DropdownMenu.Trigger>
	<DropdownMenu.Content class="w-80" align="end">
		{#if visibleJobs.length === 0}
			<div class="px-3 py-4 text-sm text-muted-foreground text-center">
				Currently no background jobs.
			</div>
		{:else}
			{#each displayedJobs as job (job.uuid)}
				{@const Icon = statusIcon(job)}
				{@const pct = progressPercent(job)}
				<div class="px-3 py-2 border-b last:border-b-0">
					<div class="flex items-start gap-2">
						<Icon
							class="w-4 h-4 mt-0.5 shrink-0 {statusColor(job)} {job.status ===
							'running'
								? 'animate-spin'
								: ''}"
						/>
						<div class="flex-1 min-w-0">
							<div class="text-sm font-medium truncate">{describeJob(job)}</div>
							{#if job.status === 'running' && job.stage}
								<div class="text-xs text-muted-foreground">
									{job.stage}{pct !== null ? ` — ${job.items_done}/${job.items_total}` : ''}
								</div>
								{#if pct !== null}
									<div class="mt-1 h-1 bg-muted rounded overflow-hidden">
										<div class="h-full bg-primary transition-all" style="width: {pct}%"></div>
									</div>
								{/if}
							{:else if job.status === 'queued'}
								<div class="text-xs text-muted-foreground">Waiting in queue…</div>
							{:else if job.status === 'failed'}
								<div class="text-xs text-destructive truncate">
									{describeError(job)}
								</div>
							{/if}
						</div>
						{#if job.status === 'failed' && typeof job.payload?.query === 'string' && isRetryable(job)}
							<button
								type="button"
								onclick={(e) => retryJob(job, e)}
								disabled={retryingUuid !== null}
								class="shrink-0 p-1 rounded hover:bg-muted transition disabled:opacity-50 disabled:cursor-not-allowed"
								aria-label="Retry job"
							>
								<RefreshCw class="w-3.5 h-3.5 {retryingUuid === job.uuid ? 'animate-spin' : ''}" />
							</button>
						{/if}
					</div>
				</div>
			{/each}
			{#if hiddenCount > 0}
				<a
					href="/library/add"
					class="block px-3 py-2 text-xs text-center text-muted-foreground hover:text-primary hover:bg-muted/50 transition"
				>
					+{hiddenCount} more in your library activity
				</a>
			{/if}
		{/if}
	</DropdownMenu.Content>
</DropdownMenu.Root>
