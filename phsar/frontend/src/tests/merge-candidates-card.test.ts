import { describe, it, expect, vi, beforeEach, afterEach } from 'vitest';
import { render, screen, fireEvent } from '@testing-library/svelte';
import MergeCandidatesCard from '../lib/components/MergeCandidatesCard.svelte';
import type { MergeCandidateListItem } from '../lib/types/api';

vi.mock('$lib/stores/auth', async () => {
	const { writable } = await import('svelte/store');
	return { token: writable('fake-token') };
});

const A_UUID = 'aaaaaaaa-aaaa-aaaa-aaaa-aaaaaaaaaaaa';
const B_UUID = 'bbbbbbbb-bbbb-bbbb-bbbb-bbbbbbbbbbbb';
const CANDIDATE_UUID = 'cccccccc-cccc-cccc-cccc-cccccccccccc';

function makeCandidate(): MergeCandidateListItem {
	return {
		uuid: CANDIDATE_UUID,
		similarity_score: 0.92,
		detected_by: 'title_studio',
		created_at: '2026-05-09T10:00:00Z',
		anime_a: {
			uuid: A_UUID,
			title: 'Anime A',
			name_eng: null,
			name_jap: null,
			media_count: 1,
			studios: ['Studio Alpha'],
			earliest_year: 2010,
			earliest_aired_from: '2010-04-01T00:00:00Z',
			rating_count: 0,
		},
		anime_b: {
			uuid: B_UUID,
			title: 'Anime B',
			name_eng: null,
			name_jap: null,
			media_count: 2,
			studios: ['Studio Beta'],
			earliest_year: 2018,
			earliest_aired_from: '2018-10-01T00:00:00Z',
			rating_count: 0,
		},
		pending_reclassifications: [],
	};
}

function jsonResponse(body: unknown, status = 200): Response {
	return {
		ok: status >= 200 && status < 300,
		status,
		json: () => Promise.resolve(body),
	} as Response;
}

describe('MergeCandidatesCard', () => {
	const originalFetch = globalThis.fetch;

	beforeEach(() => {
		globalThis.fetch = vi.fn(async () => jsonResponse([makeCandidate()])) as typeof fetch;
	});

	afterEach(() => {
		globalThis.fetch = originalFetch;
		vi.clearAllMocks();
	});

	it('default merge POSTs the visible A side as keep_uuid', async () => {
		const fetchMock = vi.fn(async (url: string, _init?: RequestInit) => {
			if (typeof url === 'string' && url.endsWith('/admin/merge-candidates')) {
				return jsonResponse([makeCandidate()]);
			}
			return jsonResponse({ surviving_anime_uuid: A_UUID });
		});
		globalThis.fetch = fetchMock as typeof fetch;

		render(MergeCandidatesCard);
		await vi.waitFor(() => expect(screen.getByText('Anime A')).toBeInTheDocument());

		await fireEvent.click(screen.getByRole('button', { name: /merge/i }));
		await fireEvent.click(screen.getByRole('button', { name: /confirm merge/i }));

		await vi.waitFor(() => {
			const mergeCall = fetchMock.mock.calls.find(([u]) => String(u).endsWith('/merge'));
			expect(mergeCall).toBeDefined();
			const body = JSON.parse((mergeCall![1] as RequestInit).body as string);
			expect(body.keep_uuid).toBe(A_UUID);
		});
	});

	it('after Swap, merge POSTs the swapped side (anime_b) as keep_uuid', async () => {
		const fetchMock = vi.fn(async (url: string, _init?: RequestInit) => {
			if (typeof url === 'string' && url.endsWith('/admin/merge-candidates')) {
				return jsonResponse([makeCandidate()]);
			}
			return jsonResponse({ surviving_anime_uuid: B_UUID });
		});
		globalThis.fetch = fetchMock as typeof fetch;

		render(MergeCandidatesCard);
		await vi.waitFor(() => expect(screen.getByText('Anime A')).toBeInTheDocument());

		await fireEvent.click(screen.getByRole('button', { name: /swap/i }));
		await fireEvent.click(screen.getByRole('button', { name: /^merge$/i }));
		await fireEvent.click(screen.getByRole('button', { name: /confirm merge/i }));

		await vi.waitFor(() => {
			const mergeCall = fetchMock.mock.calls.find(([u]) => String(u).endsWith('/merge'));
			expect(mergeCall).toBeDefined();
			const body = JSON.parse((mergeCall![1] as RequestInit).body as string);
			expect(body.keep_uuid).toBe(B_UUID);
		});
	});

	it('Refresh button does not collapse the list to a Loading state', async () => {
		let resolveSecondGet: ((value: Response) => void) | undefined;
		let getCallCount = 0;
		const fetchMock = vi.fn(async (url: string, _init?: RequestInit) => {
			if (typeof url === 'string' && url.endsWith('/admin/merge-candidates')) {
				getCallCount += 1;
				if (getCallCount === 1) {
					return jsonResponse([makeCandidate()]);
				}
				// Hold the second GET open so we can observe the UI mid-fetch.
				return new Promise<Response>((resolve) => {
					resolveSecondGet = resolve;
				});
			}
			return jsonResponse({});
		});
		globalThis.fetch = fetchMock as typeof fetch;

		render(MergeCandidatesCard);
		await vi.waitFor(() => expect(screen.getByText('Anime A')).toBeInTheDocument());

		await fireEvent.click(screen.getByRole('button', { name: /refresh/i }));

		// Mid-refresh: the each-block must still render existing rows; the
		// Loading… branch must not have replaced them.
		expect(screen.getByText('Anime A')).toBeInTheDocument();
		expect(screen.queryByText(/loading…/i)).not.toBeInTheDocument();

		resolveSecondGet?.(jsonResponse([makeCandidate()]));
		await vi.waitFor(() => expect(getCallCount).toBe(2));
	});

	it('Swap reorders the visible A/B labels', async () => {
		render(MergeCandidatesCard);
		await vi.waitFor(() => expect(screen.getByText('Anime A')).toBeInTheDocument());

		// Pre-swap: card with 'A (kept)' label sits next to 'Anime A'.
		const aKeptBefore = screen.getByText(/A \(kept\)/);
		expect(aKeptBefore.parentElement?.textContent).toContain('Anime A');

		await fireEvent.click(screen.getByRole('button', { name: /swap/i }));

		// Post-swap: 'A (kept)' now sits next to 'Anime B'.
		const aKeptAfter = screen.getByText(/A \(kept\)/);
		expect(aKeptAfter.parentElement?.textContent).toContain('Anime B');
	});
});
