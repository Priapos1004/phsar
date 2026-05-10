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

	beforeEach(() => {
		sessionStorage.setItem('phsar.bellLoginAt', SESSION_START);
		// No seen UUIDs — every finished job counts as unseen by default.
		sessionStorage.removeItem('phsar.bellSeenJobs');
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
				error_message: "Anime titled 'asdfgh' not found.",
				result_summary: { retryable: false },
			}),
		]);
		render(JobBell);
		await vi.waitFor(() => expect(globalThis.fetch).toHaveBeenCalled());
		await fireEvent.click(screen.getByLabelText('Background jobs'));
		await vi.waitFor(() => {
			expect(screen.getByText("Anime titled 'asdfgh' not found.")).toBeInTheDocument();
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
});
