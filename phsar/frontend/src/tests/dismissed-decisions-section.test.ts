/**
 * The resurface button's arm-then-confirm behaviour.
 *
 * Tested on the shared section rather than on a card, because every curation
 * queue renders this one component — so one pass covers them all, and a
 * regression in any of them fails here.
 *
 * The empty request body is asserted deliberately: the endpoint takes no
 * confirmation body, and re-gating it would make this component POST one the
 * route rejects. That is the failure the assertion exists to catch.
 */
import { describe, it, expect, vi, beforeEach, afterEach } from 'vitest';
import { render, screen, fireEvent, waitFor } from '@testing-library/svelte';
import DismissedDecisionsSection from '$lib/components/admin/DismissedDecisionsSection.svelte';
import { api } from '$lib/api';
import { createRawSnippet } from 'svelte';

vi.mock('$lib/api', () => ({
	api: { get: vi.fn(), post: vi.fn() },
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

/** Exactly the component's generic constraint: what a row means beyond `uuid`
 *  and `dismissed_at` is the parent card's business, not this component's. */
type Row = { uuid: string; dismissed_at: string | null };

const ROW: Row = {
	uuid: 'dddddddd-dddd-dddd-dddd-dddddddddddd',
	dismissed_at: '2026-09-01T10:00:00Z',
};

/** Stands in for the per-row renderer each card supplies; its content only has
 *  to be something the test can wait on. */
const row = createRawSnippet(() => ({
	render: () => '<span>Dismissed Thing</span>',
}));

function renderSection(props: Record<string, unknown> = {}) {
	return render(DismissedDecisionsSection, {
		kind: 'delete',
		listUrl: '/admin/delete-candidates/dismissed',
		basePath: '/admin/delete-candidates',
		row,
		...props,
	});
}

/** Expand the lazily-loaded section and wait for its row. */
async function expand() {
	await fireEvent.click(screen.getByText(/dismissed decisions/i));
	await waitFor(() => expect(screen.getByText('Dismissed Thing')).toBeInTheDocument());
}

describe('DismissedDecisionsSection — resurface', () => {
	beforeEach(() => {
		// Not just mockReset of the return values: call HISTORY leaks between
		// tests otherwise, and the auto-disarm case asserts post was never called.
		vi.clearAllMocks();
		vi.mocked(api.get).mockResolvedValue([ROW]);
		vi.mocked(api.post).mockResolvedValue(undefined);
	});

	afterEach(() => {
		// The arm timer outlives the test that started it.
		vi.clearAllTimers();
		vi.useRealTimers();
	});

	it('arms on the first click instead of resurfacing', async () => {
		renderSection();
		await expand();

		await fireEvent.click(screen.getByRole('button', { name: /resurface/i }));

		await waitFor(() =>
			expect(screen.getByRole('button', { name: /sure\?/i })).toBeInTheDocument(),
		);
		// The whole point of arming: one click must not have acted.
		expect(api.post).not.toHaveBeenCalled();
	});

	it('resurfaces on the second click, with no confirmation body', async () => {
		renderSection();
		await expand();

		await fireEvent.click(screen.getByRole('button', { name: /resurface/i }));
		await fireEvent.click(screen.getByRole('button', { name: /sure\?/i }));

		await waitFor(() =>
			expect(api.post).toHaveBeenCalledWith('/admin/delete-candidates/dddddddd-dddd-dddd-dddd-dddddddddddd/delete', {}),
		);
		expect(api.post).toHaveBeenCalledTimes(1);
	});

	it('disarms on its own so a stale arm cannot be confirmed later', async () => {
		vi.useFakeTimers();
		renderSection();
		await fireEvent.click(screen.getByText(/dismissed decisions/i));
		await vi.waitFor(() => expect(screen.getByText('Dismissed Thing')).toBeInTheDocument());

		await fireEvent.click(screen.getByRole('button', { name: /resurface/i }));
		expect(screen.getByRole('button', { name: /sure\?/i })).toBeInTheDocument();

		await vi.advanceTimersByTimeAsync(3500);

		expect(screen.getByRole('button', { name: /resurface/i })).toBeInTheDocument();
		expect(api.post).not.toHaveBeenCalled();
	});

	it('runs the parent re-detect so the freed candidate comes back at once', async () => {
		const onResurfaced = vi.fn();
		renderSection({ onResurfaced });
		await expand();

		await fireEvent.click(screen.getByRole('button', { name: /resurface/i }));
		await fireEvent.click(screen.getByRole('button', { name: /sure\?/i }));

		await waitFor(() => expect(onResurfaced).toHaveBeenCalledTimes(1));
	});
});
