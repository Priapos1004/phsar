import { describe, it, expect, vi, beforeEach } from 'vitest';
import { render, screen, fireEvent } from '@testing-library/svelte';
import StudioLinks from '$lib/components/StudioLinks.svelte';
import { navigateToSearch } from '$lib/utils/navigation';

vi.mock('$lib/utils/navigation', () => ({ navigateToSearch: vi.fn() }));

describe('StudioLinks', () => {
	beforeEach(() => vi.mocked(navigateToSearch).mockClear());

	it('renders a clickable button per studio', () => {
		render(StudioLinks, { props: { studios: ['MAPPA', 'Wit Studio'] } });
		expect(screen.getByRole('button', { name: /MAPPA/ })).toBeInTheDocument();
		expect(screen.getByRole('button', { name: /Wit Studio/ })).toBeInTheDocument();
	});

	it('navigates to an anime-view search filtered by the clicked studio', async () => {
		render(StudioLinks, { props: { studios: ['MAPPA', 'Wit Studio'] } });

		await fireEvent.click(screen.getByRole('button', { name: /Wit Studio/ }));

		expect(navigateToSearch).toHaveBeenCalledTimes(1);
		expect(navigateToSearch).toHaveBeenCalledWith(
			expect.objectContaining({ studio_name: ['Wit Studio'], view_type: 'anime' }),
		);
	});

	it('renders nothing when there are no studios', () => {
		const { container } = render(StudioLinks, { props: { studios: [] } });
		expect(container.querySelector('button')).toBeNull();
	});
});
