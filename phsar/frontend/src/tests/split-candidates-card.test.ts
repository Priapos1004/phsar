import { describe, it, expect, vi, beforeEach, afterEach } from 'vitest';
import { render, screen, fireEvent } from '@testing-library/svelte';
import SplitCandidatesCard from '../lib/components/SplitCandidatesCard.svelte';
import { jsonResponse } from './fixtures/response';
import type { SplitCandidateListItem } from '../lib/types/api';

vi.mock('$lib/stores/auth', async () => {
	const { writable } = await import('svelte/store');
	return { token: writable('fake-token') };
});

const SOURCE_UUID = 'aaaaaaaa-aaaa-aaaa-aaaa-aaaaaaaaaaaa';
const CANDIDATE_UUID = 'cccccccc-cccc-cccc-cccc-cccccccccccc';

function makeCandidate(): SplitCandidateListItem {
	return {
		uuid: CANDIDATE_UUID,
		detected_by: 'scrape',
		created_at: '2026-05-09T10:00:00Z',
		dismissed_at: null,
		source_anime: {
			uuid: SOURCE_UUID,
			title: 'Bundled Source',
			name_eng: null,
			name_jap: null,
			media_count: 3,
			studios: ['Studio Alpha'],
			earliest_year: 2016,
			earliest_aired_from: '2016-04-01',
			rating_count: 0,
		},
		clusters: [
			{
				suggested_anchor_mal_id: 820021,
				substance_member_mal_ids: [820021, 820022],
				bridge_edges: [[820011, 820021, 'spin-off']],
				members: [
					{
						media_uuid: 'dddddddd-dddd-dddd-dddd-dddddddddddd',
						mal_id: 820021,
						title: 'Offshoot S1',
						name_eng: null,
						name_jap: null,
						media_type: 'tv',
						relation_type: 'side_story',
					},
					{
						media_uuid: 'eeeeeeee-eeee-eeee-eeee-eeeeeeeeeeee',
						mal_id: 820022,
						title: 'Offshoot S2',
						name_eng: null,
						name_jap: null,
						media_type: 'tv',
						relation_type: 'side_story',
					},
				],
			},
		],
	};
}

/** Serves the pending list; `onAction` answers everything else.
 *  The dismissed list is not routed — DismissedDecisionsSection fetches it only
 *  on first expand, and no test here expands it. */
function routedFetch(onAction: (url: string) => Response | Promise<Response> = () => jsonResponse({})) {
	return vi.fn(async (url: string) => {
		const u = String(url);
		if (u.endsWith('/admin/split-candidates')) return jsonResponse([makeCandidate()]);
		return onAction(u);
	});
}

describe('SplitCandidatesCard', () => {
	const originalFetch = globalThis.fetch;
	let fetchMock: ReturnType<typeof routedFetch>;

	/** Installs a mock and renders; returns the mock so tests can read its calls. */
	function mount(onAction?: (url: string) => Response | Promise<Response>) {
		fetchMock = routedFetch(onAction);
		globalThis.fetch = fetchMock as unknown as typeof fetch;
		render(SplitCandidatesCard);
		return fetchMock;
	}

	const splitCalls = () => fetchMock.mock.calls.filter(([u]) => String(u).endsWith('/split'));
	const listCalls = () =>
		fetchMock.mock.calls.filter(([u]) => String(u).endsWith('/admin/split-candidates'));

	beforeEach(() => {
		globalThis.fetch = routedFetch() as unknown as typeof fetch;
	});

	afterEach(() => {
		globalThis.fetch = originalFetch;
		vi.clearAllMocks();
	});

	async function waitForCard() {
		await vi.waitFor(() => expect(screen.getByText('Bundled Source')).toBeInTheDocument());
	}

	it('renders the source anime and its cluster count', async () => {
		mount();
		await waitForCard();
		expect(screen.getByText('1 cluster')).toBeInTheDocument();
	});

	it('Split alone does not POST — only Confirm split does', async () => {
		mount(() => jsonResponse({ surviving_anime_uuid: SOURCE_UUID, new_anime_uuids: ['f1'] }));
		await waitForCard();

		// Splitting re-parents media and creates anime rows; the first click must
		// only arm the confirm step, never fire the request.
		await fireEvent.click(screen.getByRole('button', { name: /^split$/i }));
		expect(splitCalls()).toHaveLength(0);

		await fireEvent.click(screen.getByRole('button', { name: /confirm split/i }));
		await vi.waitFor(() => {
			expect(splitCalls()).toHaveLength(1);
			expect(String(splitCalls()[0][0])).toContain(CANDIDATE_UUID);
		});
	});

	it('Cancel disarms the confirm step without POSTing', async () => {
		mount();
		await waitForCard();

		await fireEvent.click(screen.getByRole('button', { name: /^split$/i }));
		await fireEvent.click(screen.getByRole('button', { name: /cancel/i }));

		expect(screen.queryByRole('button', { name: /confirm split/i })).not.toBeInTheDocument();
		expect(splitCalls()).toHaveLength(0);
	});

	it('Confirm dismiss drops the row without refetching the list', async () => {
		mount();
		await waitForCard();
		const before = listCalls().length;

		await fireEvent.click(screen.getByRole('button', { name: /^dismiss$/i }));
		await fireEvent.click(screen.getByRole('button', { name: /confirm dismiss/i }));

		// The row goes by local filter, so the pending list is not re-fetched.
		await vi.waitFor(() =>
			expect(screen.queryByText('Bundled Source')).not.toBeInTheDocument()
		);
		expect(listCalls()).toHaveLength(before);
	});

	it('cluster members stay collapsed until the summary is clicked', async () => {
		mount();
		await waitForCard();

		expect(screen.queryByText('Offshoot S1')).not.toBeInTheDocument();

		await fireEvent.click(screen.getByText(/2 media across 1 new anime row/));

		expect(screen.getByText('Offshoot S1')).toBeInTheDocument();
		expect(screen.getByText('Offshoot S2')).toBeInTheDocument();
	});

	it('Refresh does not collapse the list back to Loading', async () => {
		let resolveSecondGet: ((value: Response) => void) | undefined;
		let getCallCount = 0;
		const deferred = vi.fn(async (url: string) => {
			const u = String(url);
			if (u.endsWith('/admin/split-candidates')) {
				getCallCount += 1;
				if (getCallCount === 1) return jsonResponse([makeCandidate()]);
				// Hold the second GET open so the mid-fetch UI is observable.
				return new Promise<Response>((resolve) => {
					resolveSecondGet = resolve;
				});
			}
			return jsonResponse({});
		});
		globalThis.fetch = deferred as unknown as typeof fetch;

		render(SplitCandidatesCard);
		await vi.waitFor(() => expect(screen.getByText('Bundled Source')).toBeInTheDocument());

		await fireEvent.click(screen.getByRole('button', { name: /refresh/i }));
		await vi.waitFor(() => expect(getCallCount).toBe(2));

		// `loading` latches off after the first fetch; only `refreshing` toggles,
		// so existing rows must stay on screen while the second GET is in flight.
		expect(screen.getByText('Bundled Source')).toBeInTheDocument();
		expect(screen.queryByText(/loading…/i)).not.toBeInTheDocument();

		resolveSecondGet?.(jsonResponse([makeCandidate()]));
	});
});
