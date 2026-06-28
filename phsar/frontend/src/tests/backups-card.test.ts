import { describe, it, expect, vi, beforeEach, afterEach } from 'vitest';
import { get } from 'svelte/store';
import { render, screen, fireEvent } from '@testing-library/svelte';
import BackupsCard from '../lib/components/BackupsCard.svelte';
import type { BackupMetadata } from '../lib/types/api';

vi.mock('$lib/stores/auth', async () => {
	const { writable } = await import('svelte/store');
	return { token: writable('fake-token') };
});

function jsonResponse(body: unknown, status = 200): Response {
	return {
		ok: status >= 200 && status < 300,
		status,
		json: () => Promise.resolve(body),
	} as Response;
}

function makeBackup(overrides: Partial<BackupMetadata> = {}): BackupMetadata {
	return {
		filename: 'phsar-2026-05-09T10-00-00Z.dump',
		size_bytes: 1_048_576,
		created_at: '2026-05-09T10:00:00Z',
		integrity: 'ok',
		source: 'manual',
		content_hash: 'abc123',
		is_current: false,
		...overrides,
	};
}

describe('BackupsCard', () => {
	const originalFetch = globalThis.fetch;

	beforeEach(async () => {
		const { optimisticJobs } = await import('../lib/stores/jobs');
		optimisticJobs.set([]);
		// Reset the shared global toast slot — BackupsCard now fires its
		// "queued" toast through push() rather than a local <Toast>.
		const { activeToast } = await import('../lib/stores/toast');
		activeToast.set(null);
	});

	afterEach(() => {
		globalThis.fetch = originalFetch;
		vi.useRealTimers();
		vi.clearAllMocks();
	});

	it('clicking Create backup enqueues and shows the queued toast', async () => {
		const fetchMock = vi.fn(async (url: string, init?: RequestInit) => {
			const method = (init?.method ?? 'GET').toUpperCase();
			if (String(url).endsWith('/admin/backups') && method === 'POST') {
				return jsonResponse({ job_uuid: '11111111-1111-1111-1111-111111111111' }, 202);
			}
			if (String(url).endsWith('/admin/backups')) {
				return jsonResponse([makeBackup()]);
			}
			return jsonResponse({});
		});
		globalThis.fetch = fetchMock as typeof fetch;

		const { optimisticJobs } = await import('../lib/stores/jobs');
		const { activeToast } = await import('../lib/stores/toast');

		render(BackupsCard, { props: { currentUsername: 'admin' } });
		await vi.waitFor(() => expect(screen.getByText('Create backup')).toBeInTheDocument());

		await fireEvent.click(screen.getByText('Create backup'));

		// The toast is now global (pushToast → activeToast store, rendered by
		// the layout's ToastHost which isn't mounted here), so assert the store.
		await vi.waitFor(() => {
			expect(get(activeToast)?.message).toBe(
				"Backup queued. We'll let you know when it's ready.",
			);
		});

		const postCalls = fetchMock.mock.calls.filter(
			([_, init]) => (init as RequestInit | undefined)?.method?.toUpperCase() === 'POST',
		);
		expect(postCalls).toHaveLength(1);
		expect(String(postCalls[0][0])).toMatch(/\/admin\/backups$/);

		const seeded = get(optimisticJobs);
		expect(seeded).toHaveLength(1);
		expect(seeded[0]).toMatchObject({
			uuid: '11111111-1111-1111-1111-111111111111',
			kind: 'backup',
			status: 'queued',
		});
	});

	it('debounces double-clicks within the 5-second window', async () => {
		vi.useFakeTimers();

		const fetchMock = vi.fn(async (url: string, init?: RequestInit) => {
			const method = (init?.method ?? 'GET').toUpperCase();
			if (String(url).endsWith('/admin/backups') && method === 'POST') {
				return jsonResponse({ job_uuid: '22222222-2222-2222-2222-222222222222' }, 202);
			}
			return jsonResponse([]);
		});
		globalThis.fetch = fetchMock as typeof fetch;

		render(BackupsCard, { props: { currentUsername: 'admin' } });
		// Initial GET fires from onMount — let the microtask queue drain so the
		// component reaches its idle state before the first click.
		await vi.runOnlyPendingTimersAsync();
		const button = await vi.waitFor(() => screen.getByText('Create backup'));

		await fireEvent.click(button);
		await fireEvent.click(button);
		// Allow any pending microtasks to settle (the POST promise resolves
		// synchronously via the mock, but the setTimeout(5000) is the gate).
		await vi.runOnlyPendingTimersAsync();

		let postCalls = fetchMock.mock.calls.filter(
			([_, init]) => (init as RequestInit | undefined)?.method?.toUpperCase() === 'POST',
		);
		expect(postCalls).toHaveLength(1);

		// Advance past the 5-second debounce; the button re-enables and a
		// third click should land.
		await vi.advanceTimersByTimeAsync(5_100);
		await fireEvent.click(button);
		await vi.runOnlyPendingTimersAsync();

		postCalls = fetchMock.mock.calls.filter(
			([_, init]) => (init as RequestInit | undefined)?.method?.toUpperCase() === 'POST',
		);
		expect(postCalls).toHaveLength(2);
	});

	it('bumps jobsRefresh after a successful enqueue so the bell picks it up immediately', async () => {
		const fetchMock = vi.fn(async (url: string, init?: RequestInit) => {
			const method = (init?.method ?? 'GET').toUpperCase();
			if (String(url).endsWith('/admin/backups') && method === 'POST') {
				return jsonResponse({ job_uuid: '33333333-3333-3333-3333-333333333333' }, 202);
			}
			return jsonResponse([]);
		});
		globalThis.fetch = fetchMock as typeof fetch;

		const { get } = await import('svelte/store');
		const { jobsRefresh } = await import('../lib/stores/jobs');
		const baseline = get(jobsRefresh);

		render(BackupsCard, { props: { currentUsername: 'admin' } });
		const button = await vi.waitFor(() => screen.getByText('Create backup'));
		await fireEvent.click(button);

		// Without the bump, the bell would wait up to 30s for its idle poll
		// to surface the new queued row.
		await vi.waitFor(() => expect(get(jobsRefresh)).toBe(baseline + 1));
	});

	it('pins the is_current row to the top of the newest-first sort even when older', async () => {
		// Scenario: admin restored to an older dump. Newest-first sort would
		// normally put the older Current row below the newer non-Current ones,
		// hiding "what's actually live" below the fold. We pin Current to the
		// top of the default sort to keep it salient.
		const older = makeBackup({
			filename: 'phsar-2026-05-01T00-00-00Z.dump',
			created_at: '2026-05-01T00:00:00Z',
			source: 'cron',
			is_current: true,
		});
		const middle = makeBackup({
			filename: 'phsar-2026-05-05T00-00-00Z.dump',
			created_at: '2026-05-05T00:00:00Z',
			source: 'cron',
			is_current: false,
		});
		const newest = makeBackup({
			filename: 'phsar-2026-05-09T00-00-00Z.dump',
			created_at: '2026-05-09T00:00:00Z',
			source: 'cron',
			is_current: false,
		});

		globalThis.fetch = vi.fn(async () =>
			jsonResponse([newest, middle, older]),
		) as typeof fetch;

		render(BackupsCard, { props: { currentUsername: 'admin' } });

		// Wait for the list to render. The order of `<code>` elements in the
		// DOM mirrors the visual top-to-bottom order of dump rows.
		await vi.waitFor(() => {
			expect(screen.getByText(older.filename)).toBeInTheDocument();
		});
		const filenames = screen
			.getAllByText(/phsar-.*\.dump/)
			.map((el) => el.textContent);
		expect(filenames).toEqual([
			older.filename, // pinned because is_current
			newest.filename, // then the rest in newest-first order
			middle.filename,
		]);
	});

	it('does not reorder when no row has is_current', async () => {
		// Sanity check: without an is_current row, newest-first behaves
		// exactly as before (the pin logic is a no-op).
		const older = makeBackup({
			filename: 'phsar-2026-05-01T00-00-00Z.dump',
			created_at: '2026-05-01T00:00:00Z',
		});
		const newest = makeBackup({
			filename: 'phsar-2026-05-09T00-00-00Z.dump',
			created_at: '2026-05-09T00:00:00Z',
		});

		globalThis.fetch = vi.fn(async () =>
			jsonResponse([newest, older]),
		) as typeof fetch;

		render(BackupsCard, { props: { currentUsername: 'admin' } });
		await vi.waitFor(() => {
			expect(screen.getByText(older.filename)).toBeInTheDocument();
		});
		const filenames = screen
			.getAllByText(/phsar-.*\.dump/)
			.map((el) => el.textContent);
		expect(filenames).toEqual([newest.filename, older.filename]);
	});

	it('refreshes the dump list when backupSaved is bumped', async () => {
		let getCount = 0;
		const fetchMock = vi.fn(async (url: string, init?: RequestInit) => {
			const method = (init?.method ?? 'GET').toUpperCase();
			if (String(url).endsWith('/admin/backups') && method === 'GET') {
				getCount += 1;
				return jsonResponse(getCount === 1 ? [] : [makeBackup()]);
			}
			return jsonResponse({});
		});
		globalThis.fetch = fetchMock as typeof fetch;

		render(BackupsCard, { props: { currentUsername: 'admin' } });
		// Initial onMount fetch.
		await vi.waitFor(() => expect(getCount).toBe(1));

		const { bumpBackupSaved } = await import('../lib/stores/jobs');
		bumpBackupSaved();

		// The bump triggers a second GET; the new dump's filename appears.
		await vi.waitFor(() => expect(getCount).toBe(2));
		await vi.waitFor(() => {
			expect(screen.getByText('phsar-2026-05-09T10-00-00Z.dump')).toBeInTheDocument();
		});
	});
});
