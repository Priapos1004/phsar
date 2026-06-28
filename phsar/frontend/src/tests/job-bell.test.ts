import { describe, it, expect, vi, beforeEach, afterEach } from 'vitest';
import { render, screen, fireEvent } from '@testing-library/svelte';
import JobBell from '../lib/components/JobBell.svelte';
import type { Job } from '../lib/types/api';

vi.mock('$lib/stores/auth', async () => {
	const { writable } = await import('svelte/store');
	return { token: writable('fake-token') };
});

// All test jobs use 2026 timestamps; pin the session start before then so the
// bell's session filter doesn't hide them. seenUuids defaults to empty so
// finished jobs count as unseen for the badge tests.
const SESSION_START = '2020-01-01T00:00:00Z';

function makeJob(overrides: Partial<Job> = {}): Job {
	return {
		uuid: 'aaaaaaaa-aaaa-aaaa-aaaa-aaaaaaaaaaaa',
		kind: 'user_scrape',
		version: 1,
		status: 'queued',
		payload: { query: 'naruto' },
		stage: null,
		items_total: null,
		items_done: 0,
		result_summary: null,
		error_message: null,
		created_at: '2026-05-09T10:00:00Z',
		started_at: null,
		finished_at: null,
		...overrides,
	};
}

describe('JobBell', () => {
	const originalFetch = globalThis.fetch;

	beforeEach(async () => {
		sessionStorage.setItem('phsar.bellLoginAt', SESSION_START);
		// No seen UUIDs — every finished job counts as unseen by default.
		sessionStorage.removeItem('phsar.bellSeenJobs');
		// Clear in-memory optimistic queue so per-test state doesn't bleed.
		const { optimisticJobs } = await import('../lib/stores/jobs');
		optimisticJobs.set([]);
		// Reset the shared global toast slot so a completion toast from one
		// test isn't observed by the next.
		const { activeToast } = await import('../lib/stores/toast');
		activeToast.set(null);
		vi.useFakeTimers();
	});

	afterEach(() => {
		globalThis.fetch = originalFetch;
		sessionStorage.clear();
		vi.useRealTimers();
	});

	function mockJobsResponse(jobs: Job[]) {
		globalThis.fetch = vi.fn().mockResolvedValue({
			ok: true,
			status: 200,
			json: () => Promise.resolve(jobs),
		});
	}

	it('shows the active job count badge when jobs are running', async () => {
		mockJobsResponse([makeJob({ status: 'running' }), makeJob({ status: 'queued' })]);

		render(JobBell);
		await vi.waitFor(() => {
			expect(screen.getByText('2')).toBeInTheDocument();
		});
	});

	it('badge counts unseen finished jobs even when nothing is active', async () => {
		mockJobsResponse([
			makeJob({
				status: 'succeeded',
				finished_at: '2026-05-09T10:01:00Z',
				uuid: 'bbbbbbbb-bbbb-bbbb-bbbb-bbbbbbbbbbbb',
			}),
		]);

		render(JobBell);
		await vi.waitFor(() => {
			expect(screen.getByText('1')).toBeInTheDocument();
		});
	});

	it('opening the dropdown clears the unseen badge', async () => {
		mockJobsResponse([
			makeJob({
				status: 'succeeded',
				finished_at: '2026-05-09T10:01:00Z',
			}),
		]);

		render(JobBell);
		const trigger = await vi.waitFor(() => screen.getByLabelText('Background jobs'));
		await vi.waitFor(() => expect(screen.getByText('1')).toBeInTheDocument());

		await fireEvent.click(trigger);
		// After opening, the job's UUID is added to seenUuids; the badge
		// derived from `unseenFinished` re-evaluates to zero.
		await vi.waitFor(() => {
			expect(screen.queryByText('1')).not.toBeInTheDocument();
		});
	});

	it('persists seen UUIDs across remounts so badge stays cleared', async () => {
		const job = makeJob({
			status: 'succeeded',
			finished_at: '2026-05-09T10:01:00Z',
			uuid: 'cccccccc-cccc-cccc-cccc-cccccccccccc',
		});
		mockJobsResponse([job]);

		const { unmount } = render(JobBell);
		await vi.waitFor(() => expect(screen.getByText('1')).toBeInTheDocument());
		await fireEvent.click(screen.getByLabelText('Background jobs'));
		await vi.waitFor(() => expect(screen.queryByText('1')).not.toBeInTheDocument());
		unmount();

		// Re-render: same job comes back from /jobs/mine, but its UUID is
		// already in sessionStorage's seen set, so the badge stays empty.
		mockJobsResponse([job]);
		render(JobBell);
		await vi.waitFor(() => expect(globalThis.fetch).toHaveBeenCalled());
		expect(screen.queryByText('1')).not.toBeInTheDocument();
	});

	it('renders empty-state copy when no jobs match the session window', async () => {
		mockJobsResponse([]);
		render(JobBell);
		await vi.waitFor(() => expect(globalThis.fetch).toHaveBeenCalled());
		const trigger = screen.getByLabelText('Background jobs');
		await fireEvent.click(trigger);
		await vi.waitFor(() => {
			expect(screen.getByText('Currently no background jobs.')).toBeInTheDocument();
		});
	});

	it('hides jobs created before the session window', async () => {
		// Move the session start to right now — the 2026 test job is already
		// in the past from the bell's perspective and gets filtered out.
		sessionStorage.setItem('phsar.bellLoginAt', new Date().toISOString());
		mockJobsResponse([makeJob({ status: 'running' })]);

		render(JobBell);
		await vi.waitFor(() => expect(globalThis.fetch).toHaveBeenCalled());
		await fireEvent.click(screen.getByLabelText('Background jobs'));
		await vi.waitFor(() => {
			expect(screen.getByText('Currently no background jobs.')).toBeInTheDocument();
		});
	});

	it('shows progress bar when running with items_total set', async () => {
		mockJobsResponse([
			makeJob({ status: 'running', stage: 'Saving', items_done: 3, items_total: 10 }),
		]);
		render(JobBell);
		await vi.waitFor(() => expect(globalThis.fetch).toHaveBeenCalled());
		await fireEvent.click(screen.getByLabelText('Background jobs'));
		await vi.waitFor(() => {
			expect(screen.getByText(/Saving — 3\/10/)).toBeInTheDocument();
		});
	});

	it('shows the error message and a retry button on failed jobs', async () => {
		mockJobsResponse([
			makeJob({ status: 'failed', error_message: 'MAL timed out' }),
		]);
		render(JobBell);
		await vi.waitFor(() => expect(globalThis.fetch).toHaveBeenCalled());
		await fireEvent.click(screen.getByLabelText('Background jobs'));
		await vi.waitFor(() => {
			expect(screen.getByText('MAL timed out')).toBeInTheDocument();
			expect(screen.getByLabelText('Retry job')).toBeInTheDocument();
		});
	});

	it('renders friendly copy for upstream-outage failures instead of the raw 504 message', async () => {
		mockJobsResponse([
			makeJob({
				status: 'failed',
				error_message: "Server error '504 Gateway Time-out' for url 'https://api.jikan.moe/v4/anime?q=Spoiled&limit=3'",
				result_summary: { retryable: true, error_category: 'upstream_outage' },
			}),
		]);
		render(JobBell);
		await vi.waitFor(() => expect(globalThis.fetch).toHaveBeenCalled());
		await fireEvent.click(screen.getByLabelText('Background jobs'));
		await vi.waitFor(() => {
			expect(
				screen.getByText('Anime database is temporarily unavailable. Please retry in a few minutes.'),
			).toBeInTheDocument();
			// Raw upstream message hidden so users don't see implementation details.
			expect(screen.queryByText(/504 Gateway Time-out/)).not.toBeInTheDocument();
		});
	});

	it('caps the dropdown at 5 entries and surfaces a "+N more" link', async () => {
		// 7 finished jobs: the bell should render 5 + a link pointing at
		// /library/add for the remaining 2. The badge counts the full set
		// of unseen finishes (7) since the API still returns them.
		const jobs = Array.from({ length: 7 }, (_, i) =>
			makeJob({
				status: 'succeeded',
				finished_at: `2026-05-09T10:0${i}:00Z`,
				uuid: `dddddddd-dddd-dddd-dddd-${i.toString().padStart(12, '0')}`,
				payload: { query: `query-${i}` },
			}),
		);
		mockJobsResponse(jobs);
		render(JobBell);
		await vi.waitFor(() => expect(globalThis.fetch).toHaveBeenCalled());
		await fireEvent.click(screen.getByLabelText('Background jobs'));
		await vi.waitFor(() => {
			expect(screen.getByText('+2 more in your library activity')).toBeInTheDocument();
		});
		// Exactly 5 of the 7 unique queries are rendered in the dropdown.
		const renderedQueries = jobs
			.map((j) => `Add: "${j.payload.query as string}"`)
			.filter((label) => screen.queryByText(label) !== null);
		expect(renderedQueries).toHaveLength(5);
	});

	it('does not show the "+N more" link when all jobs fit in the cap', async () => {
		mockJobsResponse([
			makeJob({ status: 'succeeded', finished_at: '2026-05-09T10:00:00Z' }),
		]);
		render(JobBell);
		await vi.waitFor(() => expect(globalThis.fetch).toHaveBeenCalled());
		await fireEvent.click(screen.getByLabelText('Background jobs'));
		await vi.waitFor(() => expect(screen.queryByText(/more in your library activity/)).not.toBeInTheDocument());
	});

	it('hides the retry button when the failure is marked non-retryable', async () => {
		// PermanentPhsarError on the backend writes retryable: false into
		// result_summary; the bell uses that to suppress retry for failures
		// that would deterministically fail again (anime not found, etc.).
		mockJobsResponse([
			makeJob({
				status: 'failed',
				error_message: "No new anime matched 'asdfgh' on MAL.",
				result_summary: { retryable: false },
			}),
		]);
		render(JobBell);
		await vi.waitFor(() => expect(globalThis.fetch).toHaveBeenCalled());
		await fireEvent.click(screen.getByLabelText('Background jobs'));
		await vi.waitFor(() => {
			expect(screen.getByText("No new anime matched 'asdfgh' on MAL.")).toBeInTheDocument();
		});
		expect(screen.queryByLabelText('Retry job')).not.toBeInTheDocument();
	});

	it('stops polling on 401 (logged out)', async () => {
		const fetchMock = vi.fn().mockResolvedValue({
			ok: false,
			status: 401,
			json: () => Promise.resolve({ detail: 'Unauthorized' }),
		});
		globalThis.fetch = fetchMock;

		render(JobBell);
		await vi.waitFor(() => {
			expect(fetchMock).toHaveBeenCalledTimes(1);
		});

		// Advance well past both polling cadences — fetch should not be re-invoked.
		await vi.advanceTimersByTimeAsync(60_000);
		expect(fetchMock).toHaveBeenCalledTimes(1);
	});

	it('refetches when the jobsRefresh store is bumped', async () => {
		const fetchMock = vi.fn().mockResolvedValue({
			ok: true,
			status: 200,
			json: () => Promise.resolve([]),
		});
		globalThis.fetch = fetchMock;

		render(JobBell);
		await vi.waitFor(() => expect(fetchMock).toHaveBeenCalledTimes(1));

		const { bumpJobsRefresh } = await import('../lib/stores/jobs');
		bumpJobsRefresh();
		await vi.waitFor(() => {
			expect(fetchMock).toHaveBeenCalledTimes(2);
		});
	});

	it('bumps librarySaved exactly once per newly-succeeded job', async () => {
		// vi.waitFor doesn't play well with fake timers across module-scoped
		// store updates here — use real timers for this assertion.
		vi.useRealTimers();

		// The bell observes the same job in successive polls but should only
		// announce it once — otherwise /library/add would refetch on every tick.
		const succeeded = makeJob({
			status: 'succeeded',
			finished_at: '2026-05-09T10:01:00Z',
			uuid: 'dddddddd-dddd-dddd-dddd-dddddddddddd',
		});
		mockJobsResponse([succeeded]);

		const { get } = await import('svelte/store');
		const { librarySaved, bumpJobsRefresh } = await import('../lib/stores/jobs');
		const baseline = get(librarySaved);

		render(JobBell);
		await vi.waitFor(() => expect(get(librarySaved)).toBe(baseline + 1));

		// Trigger a second poll with the same data — no additional bump.
		bumpJobsRefresh();
		await new Promise((r) => setTimeout(r, 50));
		expect(get(librarySaved)).toBe(baseline + 1);
	});

	it('renders the backup kind label for queued backup jobs', async () => {
		mockJobsResponse([
			makeJob({
				kind: 'backup',
				status: 'queued',
				payload: { source: 'manual' },
				uuid: 'eeeeeeee-eeee-eeee-eeee-eeeeeeeeeeee',
			}),
		]);
		render(JobBell);
		await vi.waitFor(() => expect(globalThis.fetch).toHaveBeenCalled());
		await fireEvent.click(screen.getByLabelText('Background jobs'));
		await vi.waitFor(() => {
			expect(screen.getByText('Backup')).toBeInTheDocument();
		});
		// No fuzzy "Add: …" copy leaking into backup rows.
		expect(screen.queryByText(/Add:/)).not.toBeInTheDocument();
	});

	it('renders the dump size on a succeeded backup', async () => {
		mockJobsResponse([
			makeJob({
				kind: 'backup',
				status: 'succeeded',
				finished_at: '2026-05-09T10:05:00Z',
				payload: { source: 'manual' },
				result_summary: {
					filename: 'phsar-2026-05-09T10-04-00Z.dump',
					size_bytes: 12_500_000,
					integrity: 'ok',
					source: 'manual',
					deduped_against: null,
				},
				uuid: 'ffffffff-ffff-ffff-ffff-ffffffffffff',
			}),
		]);
		render(JobBell);
		await vi.waitFor(() => expect(globalThis.fetch).toHaveBeenCalled());
		await fireEvent.click(screen.getByLabelText('Background jobs'));
		await vi.waitFor(() => {
			// formatBytes(12_500_000) = "11.9 MB" — see lib/utils/formatString.ts.
			expect(screen.getByText('Backup ready (11.9 MB)')).toBeInTheDocument();
		});
	});

	it('renders the deduped copy when result_summary.deduped_against is set', async () => {
		mockJobsResponse([
			makeJob({
				kind: 'backup',
				status: 'succeeded',
				finished_at: '2026-05-09T10:05:00Z',
				payload: { source: 'manual' },
				result_summary: {
					filename: 'phsar-2026-05-08T10-00-00Z.dump',
					size_bytes: 12_500_000,
					integrity: 'ok',
					source: 'manual',
					deduped_against: 'phsar-2026-05-08T10-00-00Z.dump',
				},
				uuid: '11111111-1111-1111-1111-111111111111',
			}),
		]);
		render(JobBell);
		await vi.waitFor(() => expect(globalThis.fetch).toHaveBeenCalled());
		await fireEvent.click(screen.getByLabelText('Background jobs'));
		await vi.waitFor(() => {
			expect(
				screen.getByText('Re-confirmed existing dump (no new data)'),
			).toBeInTheDocument();
		});
		// The size copy is suppressed when the run was a dedupe hit.
		expect(screen.queryByText(/Backup ready/)).not.toBeInTheDocument();
	});

	it('renders friendly copy and a retry button for backup_disk_full', async () => {
		mockJobsResponse([
			makeJob({
				kind: 'backup',
				status: 'failed',
				payload: { source: 'manual' },
				error_message: 'Insufficient disk space on backup volume: 12 MB free, need at least 500 MB.',
				result_summary: { retryable: true, error_category: 'backup_disk_full' },
				uuid: '22222222-2222-2222-2222-222222222222',
			}),
		]);
		render(JobBell);
		await vi.waitFor(() => expect(globalThis.fetch).toHaveBeenCalled());
		await fireEvent.click(screen.getByLabelText('Background jobs'));
		await vi.waitFor(() => {
			expect(
				screen.getByText('Backup volume is full. Free disk space and retry.'),
			).toBeInTheDocument();
			expect(screen.getByLabelText('Retry job')).toBeInTheDocument();
		});
		// Raw stderr-style message hidden in favor of the friendly copy.
		expect(screen.queryByText(/MB free, need at least/)).not.toBeInTheDocument();
	});

	it('renders friendly copy and a retry button for backup_corrupt', async () => {
		mockJobsResponse([
			makeJob({
				kind: 'backup',
				status: 'failed',
				payload: { source: 'manual' },
				error_message: "Backup 'phsar-...dump' failed integrity check: pg_restore: error: ...",
				result_summary: { retryable: true, error_category: 'backup_corrupt' },
				uuid: '33333333-3333-3333-3333-333333333333',
			}),
		]);
		render(JobBell);
		await vi.waitFor(() => expect(globalThis.fetch).toHaveBeenCalled());
		await fireEvent.click(screen.getByLabelText('Background jobs'));
		await vi.waitFor(() => {
			expect(
				screen.getByText(
					'Backup archive failed integrity check. Retrying may produce a clean dump.',
				),
			).toBeInTheDocument();
			expect(screen.getByLabelText('Retry job')).toBeInTheDocument();
		});
	});

	it('retry on a failed backup posts /admin/backups with the original label', async () => {
		// First fetch: surface the failed job. Second fetch (during retry): the
		// retry POST itself. Third fetch: the post-retry refresh of /jobs/mine.
		const fetchMock = vi
			.fn()
			.mockResolvedValueOnce({
				ok: true,
				status: 200,
				json: () => Promise.resolve([
					makeJob({
						kind: 'backup',
						status: 'failed',
						payload: { source: 'manual', label: 'pre-upgrade' },
						error_message: "Backup 'x.dump' failed integrity check",
						result_summary: { retryable: true, error_category: 'backup_corrupt' },
						uuid: '44444444-4444-4444-4444-444444444444',
					}),
				]),
			})
			.mockResolvedValueOnce({
				ok: true,
				status: 202,
				json: () => Promise.resolve({ job_uuid: '55555555-5555-5555-5555-555555555555' }),
			})
			.mockResolvedValueOnce({
				ok: true,
				status: 200,
				json: () => Promise.resolve([]),
			});
		globalThis.fetch = fetchMock;

		render(JobBell);
		await vi.waitFor(() => expect(screen.getByLabelText('Background jobs')).toBeInTheDocument());
		await fireEvent.click(screen.getByLabelText('Background jobs'));
		const retry = await vi.waitFor(() => screen.getByLabelText('Retry job'));
		await fireEvent.click(retry);

		await vi.waitFor(() => expect(fetchMock).toHaveBeenCalledTimes(3));
		const postCall = fetchMock.mock.calls[1];
		expect(postCall[0]).toMatch(/\/admin\/backups$/);
		const body = JSON.parse(postCall[1].body);
		expect(body).toEqual({ label: 'pre-upgrade' });
	});

	it('renders an optimistic job pushed into the store before the next fetch', async () => {
		mockJobsResponse([]);
		render(JobBell);
		await vi.waitFor(() => expect(globalThis.fetch).toHaveBeenCalled());

		const { addOptimisticJob } = await import('../lib/stores/jobs');
		addOptimisticJob(
			makeJob({
				kind: 'backup',
				status: 'queued',
				payload: { source: 'manual' },
				uuid: '77777777-7777-7777-7777-777777777777',
				created_at: new Date().toISOString(),
			}),
		);

		await fireEvent.click(screen.getByLabelText('Background jobs'));
		await vi.waitFor(() => {
			expect(screen.getByText('Backup')).toBeInTheDocument();
		});
	});

	it('reconciles the optimistic row when the real job lands in /jobs/mine', async () => {
		const realJob = makeJob({
			kind: 'backup',
			status: 'running',
			stage: 'Dumping',
			payload: { source: 'manual' },
			uuid: '88888888-8888-8888-8888-888888888888',
		});
		// First fetch returns empty; second (after bumpJobsRefresh) returns the
		// real job — same UUID as the optimistic stub.
		const fetchMock = vi
			.fn()
			.mockResolvedValueOnce({ ok: true, status: 200, json: () => Promise.resolve([]) })
			.mockResolvedValue({ ok: true, status: 200, json: () => Promise.resolve([realJob]) });
		globalThis.fetch = fetchMock;

		const { addOptimisticJob, bumpJobsRefresh, optimisticJobs } = await import(
			'../lib/stores/jobs'
		);
		const { get } = await import('svelte/store');

		render(JobBell);
		await vi.waitFor(() => expect(fetchMock).toHaveBeenCalledTimes(1));

		addOptimisticJob(
			makeJob({
				kind: 'backup',
				status: 'queued',
				payload: { source: 'manual' },
				uuid: '88888888-8888-8888-8888-888888888888',
				created_at: new Date().toISOString(),
			}),
		);
		expect(get(optimisticJobs)).toHaveLength(1);

		bumpJobsRefresh();
		await vi.waitFor(() => expect(fetchMock).toHaveBeenCalledTimes(2));
		// Once /jobs/mine returns the real row, the optimistic copy is pruned.
		await vi.waitFor(() => expect(get(optimisticJobs)).toHaveLength(0));

		// The dropdown shows exactly one Backup row (the real one with its stage).
		await fireEvent.click(screen.getByLabelText('Background jobs'));
		await vi.waitFor(() => {
			expect(screen.getAllByText('Backup')).toHaveLength(1);
			expect(screen.getByText(/Dumping/)).toBeInTheDocument();
		});
	});

	it('bumps backupSaved exactly once per newly-succeeded backup', async () => {
		vi.useRealTimers();

		const succeeded = makeJob({
			kind: 'backup',
			status: 'succeeded',
			finished_at: '2026-05-09T10:05:00Z',
			payload: { source: 'manual' },
			result_summary: {
				filename: 'phsar-2026-05-09T10-04-00Z.dump',
				size_bytes: 1024,
				integrity: 'ok',
				source: 'manual',
				deduped_against: null,
			},
			uuid: '66666666-6666-6666-6666-666666666666',
		});
		mockJobsResponse([succeeded]);

		const { get } = await import('svelte/store');
		const { backupSaved, bumpJobsRefresh } = await import('../lib/stores/jobs');
		const baseline = get(backupSaved);

		render(JobBell);
		await vi.waitFor(() => expect(get(backupSaved)).toBe(baseline + 1));

		bumpJobsRefresh();
		await new Promise((r) => setTimeout(r, 50));
		expect(get(backupSaved)).toBe(baseline + 1);
	});

	it('renders a succeeded scrape row as a link to /library/add', async () => {
		mockJobsResponse([
			makeJob({ status: 'succeeded', finished_at: '2026-05-09T10:01:00Z' }),
		]);
		render(JobBell);
		await vi.waitFor(() => expect(globalThis.fetch).toHaveBeenCalled());
		await fireEvent.click(screen.getByLabelText('Background jobs'));
		// The dropdown content is portaled; query by text and walk up to the
		// wrapping anchor rather than getByRole (which filters the portal).
		const row = await vi.waitFor(() => screen.getByText('Add: "naruto"'));
		const link = row.closest('a');
		expect(link).not.toBeNull();
		expect(link).toHaveAttribute('href', '/library/add');
	});

	it('renders a succeeded backup row as a link to the admin backups tab', async () => {
		mockJobsResponse([
			makeJob({
				kind: 'backup',
				status: 'succeeded',
				finished_at: '2026-05-09T10:05:00Z',
				payload: { source: 'manual' },
				result_summary: {
					filename: 'phsar-2026-05-09T10-04-00Z.dump',
					size_bytes: 1024,
					integrity: 'ok',
					source: 'manual',
					deduped_against: null,
				},
				uuid: '99999999-9999-9999-9999-999999999999',
			}),
		]);
		render(JobBell);
		await vi.waitFor(() => expect(globalThis.fetch).toHaveBeenCalled());
		await fireEvent.click(screen.getByLabelText('Background jobs'));
		const row = await vi.waitFor(() => screen.getByText('Backup'));
		const link = row.closest('a');
		expect(link).not.toBeNull();
		expect(link).toHaveAttribute('href', '/admin?tab=backups');
	});

	it('clears the badge for a still-running job once the bell is opened', async () => {
		// The dismissible-while-fetching behavior: opening the bell acknowledges
		// running jobs too, so the badge can clear before the job finishes.
		mockJobsResponse([makeJob({ status: 'running' })]);
		render(JobBell);
		const trigger = await vi.waitFor(() => screen.getByLabelText('Background jobs'));
		await vi.waitFor(() => expect(screen.getByText('1')).toBeInTheDocument());

		await fireEvent.click(trigger);
		await vi.waitFor(() => {
			expect(screen.queryByText('1')).not.toBeInTheDocument();
		});
	});

	it('pushes a green success toast when a watched scrape transitions to succeeded', async () => {
		const running = makeJob({ status: 'running', uuid: 'a1a1a1a1-a1a1-a1a1-a1a1-a1a1a1a1a1a1' });
		const succeeded = makeJob({
			status: 'succeeded',
			finished_at: '2026-05-09T10:01:00Z',
			uuid: 'a1a1a1a1-a1a1-a1a1-a1a1-a1a1a1a1a1a1',
		});
		const fetchMock = vi
			.fn()
			.mockResolvedValueOnce({ ok: true, status: 200, json: () => Promise.resolve([running]) })
			.mockResolvedValue({ ok: true, status: 200, json: () => Promise.resolve([succeeded]) });
		globalThis.fetch = fetchMock;

		const { activeToast } = await import('../lib/stores/toast');
		const { get } = await import('svelte/store');

		render(JobBell);
		await vi.waitFor(() => expect(fetchMock).toHaveBeenCalledTimes(1));
		// First fetch saw it running — no transition yet.
		expect(get(activeToast)).toBeNull();

		// Next active poll (2s) returns the succeeded row → transition → toast.
		await vi.advanceTimersByTimeAsync(2000);
		await vi.waitFor(() => {
			const t = get(activeToast);
			expect(t?.variant).toBe('success');
			expect(t?.message).toContain('naruto');
		});
	});

	it('pushes a red error toast when a watched scrape transitions to failed', async () => {
		const running = makeJob({ status: 'running', uuid: 'b2b2b2b2-b2b2-b2b2-b2b2-b2b2b2b2b2b2' });
		const failed = makeJob({
			status: 'failed',
			error_message: 'MAL timed out',
			uuid: 'b2b2b2b2-b2b2-b2b2-b2b2-b2b2b2b2b2b2',
		});
		const fetchMock = vi
			.fn()
			.mockResolvedValueOnce({ ok: true, status: 200, json: () => Promise.resolve([running]) })
			.mockResolvedValue({ ok: true, status: 200, json: () => Promise.resolve([failed]) });
		globalThis.fetch = fetchMock;

		const { activeToast } = await import('../lib/stores/toast');
		const { get } = await import('svelte/store');

		render(JobBell);
		await vi.waitFor(() => expect(fetchMock).toHaveBeenCalledTimes(1));
		await vi.advanceTimersByTimeAsync(2000);
		await vi.waitFor(() => {
			expect(get(activeToast)?.variant).toBe('error');
		});
	});

	it('does not toast a job that is already finished on the first fetch', async () => {
		// No active→finished transition was ever observed (the bell first saw it
		// already succeeded), so the toast must stay silent.
		mockJobsResponse([
			makeJob({ status: 'succeeded', finished_at: '2026-05-09T10:01:00Z' }),
		]);
		const { activeToast } = await import('../lib/stores/toast');
		const { get } = await import('svelte/store');

		render(JobBell);
		await vi.waitFor(() => expect(globalThis.fetch).toHaveBeenCalled());
		// Idle poll cadence (30s) — advance past it; same row comes back, still
		// no transition.
		await vi.advanceTimersByTimeAsync(30_000);
		expect(get(activeToast)).toBeNull();
	});
});
