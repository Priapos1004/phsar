import { describe, it, expect, vi, beforeEach, afterEach } from 'vitest';
import { render, waitFor } from '@testing-library/svelte';
import AdminJobsLogTab from '$lib/components/admin/AdminJobsLogTab.svelte';
import { api } from '$lib/api';
import { clearJobsFilter } from '$lib/stores/adminJobsFilter';
import type { AdminJobsPage } from '$lib/types/api';

vi.mock('$lib/api', () => ({
	api: { get: vi.fn() },
	ApiError: class extends Error {
		status: number;
		detail: string;
		constructor(status: number, detail: string) {
			super(detail);
			this.status = status;
			this.detail = detail;
		}
	},
}));

const IDLE_POLL_MS = 30000;

function emptyPage(): AdminJobsPage {
	return { items: [], total: 0, limit: 50, offset: 0 };
}

/** Let the pending load() settle before asserting on call counts. */
async function settle() {
	await vi.advanceTimersByTimeAsync(0);
}

describe('AdminJobsLogTab poll gating', () => {
	beforeEach(() => {
		clearJobsFilter();
		vi.mocked(api.get).mockResolvedValue(emptyPage());
		vi.useFakeTimers();
	});

	afterEach(() => {
		vi.useRealTimers();
		vi.clearAllMocks();
	});

	it('still loads once on mount while hidden, so a tab switch is instant', async () => {
		render(AdminJobsLogTab, { props: { visible: false } });
		await settle();
		expect(api.get).toHaveBeenCalledTimes(1);
	});

	it('does not poll while hidden', async () => {
		render(AdminJobsLogTab, { props: { visible: false } });
		await settle();
		vi.mocked(api.get).mockClear();

		// Four idle intervals' worth of time: an ungated poll would have fired.
		await vi.advanceTimersByTimeAsync(IDLE_POLL_MS * 4);
		expect(api.get).not.toHaveBeenCalled();
	});

	it('polls on the idle interval while visible', async () => {
		render(AdminJobsLogTab, { props: { visible: true } });
		await settle();
		vi.mocked(api.get).mockClear();

		await vi.advanceTimersByTimeAsync(IDLE_POLL_MS);
		expect(api.get).toHaveBeenCalledTimes(1);
	});

	it('does not double-fetch on mount when already visible', async () => {
		render(AdminJobsLogTab, { props: { visible: true } });
		await settle();
		// The filter effect owns the first load; the poll effect must not add
		// its catch-up fetch on top of it.
		expect(api.get).toHaveBeenCalledTimes(1);
	});

	it('catches up on re-show once a poll tick has been missed', async () => {
		const { rerender } = render(AdminJobsLogTab, { props: { visible: false } });
		await settle();
		await vi.advanceTimersByTimeAsync(IDLE_POLL_MS);
		vi.mocked(api.get).mockClear();

		await rerender({ visible: true });
		await waitFor(() => expect(api.get).toHaveBeenCalledTimes(1));
	});

	it('does not catch up on a detour shorter than one tick', async () => {
		// Flicking through tabs must not fetch on every return — that would
		// cost more than the ungated poll this gating replaced.
		const { rerender } = render(AdminJobsLogTab, { props: { visible: true } });
		await settle();
		vi.mocked(api.get).mockClear();

		await rerender({ visible: false });
		await vi.advanceTimersByTimeAsync(1000);
		await rerender({ visible: true });
		await settle();
		expect(api.get).not.toHaveBeenCalled();
	});

	it('stops polling again when the tab is hidden', async () => {
		const { rerender } = render(AdminJobsLogTab, { props: { visible: true } });
		await settle();

		await rerender({ visible: false });
		await settle();
		vi.mocked(api.get).mockClear();

		await vi.advanceTimersByTimeAsync(IDLE_POLL_MS * 4);
		expect(api.get).not.toHaveBeenCalled();
	});
});
