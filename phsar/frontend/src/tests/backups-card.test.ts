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

// The list endpoint returns an envelope: the live schema revision + the rows.
function backupList(rows: BackupMetadata[], dbRevision: string | null = null) {
	return { db_revision: dbRevision, backups: rows };
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
		status: 'ok',
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
				return jsonResponse(backupList([makeBackup()]));
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
			return jsonResponse(backupList([]));
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
			return jsonResponse(backupList([]));
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
			jsonResponse(backupList([newest, middle, older])),
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
			jsonResponse(backupList([newest, older])),
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

	// "ok" claims restorable-right-now, so it needs an intact file AND the live
	// schema. These pin the three-way outcome — a legacy dump with no recorded
	// revision must not be accused of being stale.
	async function renderWithBackups(rows: BackupMetadata[], dbRevision: string | null = null) {
		globalThis.fetch = vi.fn(async (url: string) =>
			String(url).endsWith('/admin/backups')
				? jsonResponse(backupList(rows, dbRevision))
				: jsonResponse({}),
		) as unknown as typeof fetch;
		render(BackupsCard, { props: { currentUsername: 'admin' } });
		await vi.waitFor(() => expect(screen.getByText(rows[0].filename)).toBeInTheDocument());
	}

	it('shows "ok" for an intact dump on the live schema', async () => {
		await renderWithBackups(
			[makeBackup({ alembic_revision: 'd9e4a1c7b3f2', schema_current: true, status: 'ok' })],
			'd9e4a1c7b3f2',
		);
		expect(screen.getByText('ok')).toBeInTheDocument();
		expect(screen.queryByText('schema outdated')).not.toBeInTheDocument();
		// Twice: once on the row (beside its size) and once as the header's
		// live-schema reference, which now comes from the response envelope.
		expect(screen.getAllByText('d9e4a1c7')).toHaveLength(2);
	});

	it('shows the live schema as unknown when the server could not read it', async () => {
		// `db_revision: null` means read_db_revision() failed — a property of the
		// SERVER, not of the dumps. Scoped to the controls row because a dump with
		// no verdict renders its own `unknown` badge too.
		await renderWithBackups(
			[makeBackup({ alembic_revision: 'd9e4a1c7b3f2', schema_current: null, status: 'unknown' })],
			null,
		);
		expect(screen.getByTestId('live-db-revision')).toHaveTextContent('unknown');
	});

	it('replaces "ok" with "schema outdated" on a revision mismatch', async () => {
		await renderWithBackups(
			[makeBackup({ alembic_revision: 'b7f3a1c9d2e5', schema_current: false, status: 'outdated' })],
			'd9e4a1c7b3f2',
		);
		expect(screen.getByText('schema outdated')).toBeInTheDocument();
		expect(screen.queryByText('ok')).not.toBeInTheDocument();
	});

	it('does NOT show "ok" for a dump with no recorded revision', async () => {
		// The server composes `unknown` for a revision-less dump precisely so it is
		// never advertised as restorable. Fixtures here must stay states the server can
		// actually emit: `status: 'ok'` with `schema_current: null` is impossible, and
		// asserting on it would pass while the card composed its own verdict.
		await renderWithBackups(
			[makeBackup({ alembic_revision: null, schema_current: null, status: 'unknown' })],
			'd9e4a1c7b3f2',
		);
		expect(screen.queryByText('ok')).not.toBeInTheDocument();
		expect(screen.queryByText('schema outdated')).not.toBeInTheDocument();
	});

	it('refreshes the dump list when backupSaved is bumped', async () => {
		let getCount = 0;
		const fetchMock = vi.fn(async (url: string, init?: RequestInit) => {
			const method = (init?.method ?? 'GET').toUpperCase();
			if (String(url).endsWith('/admin/backups') && method === 'GET') {
				getCount += 1;
				return jsonResponse(backupList(getCount === 1 ? [] : [makeBackup()]));
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
