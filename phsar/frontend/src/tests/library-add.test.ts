import { describe, it, expect, vi, beforeEach, afterEach } from 'vitest';
import { render, screen, fireEvent } from '@testing-library/svelte';
import LibraryAddPage from '../routes/library/add/+page.svelte';

vi.mock('$lib/stores/auth', async () => {
	const { writable } = await import('svelte/store');
	return { token: writable('fake-token') };
});

interface RecentItem {
	uuid: string;
	title: string;
	cover_image: string | null;
	created_at: string;
}

describe('Library Add page', () => {
	const originalFetch = globalThis.fetch;

	beforeEach(() => {
		vi.useFakeTimers();
	});

	afterEach(() => {
		globalThis.fetch = originalFetch;
		vi.useRealTimers();
	});

	function mockRecent(items: RecentItem[]) {
		globalThis.fetch = vi.fn().mockImplementation((url: string) => {
			if (url.includes('/library/recent')) {
				return Promise.resolve({
					ok: true,
					status: 200,
					json: () => Promise.resolve(items),
				});
			}
			return Promise.resolve({
				ok: true,
				status: 200,
				json: () => Promise.resolve({}),
			});
		});
	}

	it('renders the form title + button', () => {
		mockRecent([]);
		render(LibraryAddPage);
		// Card.Title from shadcn-svelte renders a <div>, not a <heading>; match
		// by text instead so the test isn't coupled to the Card component's tag.
		expect(screen.getByText('Add to Library')).toBeInTheDocument();
		expect(screen.getByRole('button', { name: /Add to library/i })).toBeInTheDocument();
	});

	it('disables the submit button until 4 characters are typed', async () => {
		mockRecent([]);
		render(LibraryAddPage);

		const input = screen.getByPlaceholderText(/Naruto/i) as HTMLInputElement;
		const button = screen.getByRole('button', { name: /Add to library/i });
		expect(button).toBeDisabled();

		await fireEvent.input(input, { target: { value: 'fma' } });
		expect(button).toBeDisabled();

		await fireEvent.input(input, { target: { value: 'fmab' } });
		expect(button).not.toBeDisabled();
	});

	it('renders recent additions with correct anime detail links', async () => {
		const items: RecentItem[] = [
			{
				uuid: 'aaaaaaaa-aaaa-aaaa-aaaa-aaaaaaaaaaaa',
				title: 'Naruto',
				cover_image: 'https://example.com/cover.jpg',
				created_at: '2026-05-01T12:00:00Z',
			},
		];
		mockRecent(items);
		render(LibraryAddPage);

		await vi.waitFor(() => {
			const link = screen.getByRole('link', { name: /Naruto/ });
			// buildDetailHref('anime', uuid, null) → "/anime?uuid={uuid}"
			expect(link).toHaveAttribute(
				'href',
				`/anime?uuid=${items[0].uuid}`,
			);
		});
	});

	it('shows empty-state when there are no recent additions', async () => {
		mockRecent([]);
		render(LibraryAddPage);
		await vi.waitFor(() => {
			expect(screen.getByText(/Nothing here yet/)).toBeInTheDocument();
		});
	});

	it('refreshes recent additions when librarySaved bumps', async () => {
		const recentMock = vi.fn().mockResolvedValue({
			ok: true,
			status: 200,
			json: () => Promise.resolve([]),
		});
		globalThis.fetch = recentMock;

		render(LibraryAddPage);
		await vi.waitFor(() => expect(recentMock).toHaveBeenCalledTimes(1));

		const { bumpLibrarySaved } = await import('../lib/stores/jobs');
		bumpLibrarySaved();
		await vi.waitFor(() => {
			expect(recentMock).toHaveBeenCalledTimes(2);
		});
	});
});
