import { describe, it, expect, vi, beforeEach } from 'vitest';
import { render, screen, fireEvent } from '@testing-library/svelte';
import StudioLinks from '$lib/components/StudioLinks.svelte';
import { searchByStudio } from '$lib/utils/navigation';

// Studio search is delegated to the shared searchByStudio helper (its filter shape
// is covered in navigation.test.ts); here we just verify the click wires through.
vi.mock('$lib/utils/navigation', () => ({ searchByStudio: vi.fn() }));

describe('StudioLinks', () => {
	beforeEach(() => vi.mocked(searchByStudio).mockClear());

	it('renders a clickable button per studio', () => {
		render(StudioLinks, { props: { studios: ['MAPPA', 'Wit Studio'] } });
		expect(screen.getByRole('button', { name: /MAPPA/ })).toBeInTheDocument();
		expect(screen.getByRole('button', { name: /Wit Studio/ })).toBeInTheDocument();
	});

	it('searches for the clicked studio', async () => {
		render(StudioLinks, { props: { studios: ['MAPPA', 'Wit Studio'] } });

		await fireEvent.click(screen.getByRole('button', { name: /Wit Studio/ }));

		expect(searchByStudio).toHaveBeenCalledTimes(1);
		expect(searchByStudio).toHaveBeenCalledWith('Wit Studio');
	});

	it('renders nothing when there are no studios', () => {
		const { container } = render(StudioLinks, { props: { studios: [] } });
		expect(container.querySelector('button')).toBeNull();
	});
});
