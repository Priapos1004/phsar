import { describe, it, expect, vi } from 'vitest';
import { render, screen, fireEvent } from '@testing-library/svelte';
import SearchLinks from '$lib/components/SearchLinks.svelte';

describe('SearchLinks', () => {
	it('renders the label and a clickable button per value', () => {
		render(SearchLinks, { props: { label: 'Studio', values: ['MAPPA', 'Wit Studio'], onSelect: vi.fn() } });
		expect(screen.getByText('Studio')).toBeInTheDocument();
		expect(screen.getByRole('button', { name: /MAPPA/ })).toBeInTheDocument();
		expect(screen.getByRole('button', { name: /Wit Studio/ })).toBeInTheDocument();
	});

	it('hands the clicked value to onSelect', async () => {
		const onSelect = vi.fn();
		render(SearchLinks, { props: { label: 'Studio', values: ['MAPPA', 'Wit Studio'], onSelect } });

		await fireEvent.click(screen.getByRole('button', { name: /Wit Studio/ }));

		expect(onSelect).toHaveBeenCalledTimes(1);
		expect(onSelect).toHaveBeenCalledWith('Wit Studio');
	});

	it('renders nothing when there are no values', () => {
		const { container } = render(SearchLinks, { props: { label: 'Source', values: [], onSelect: vi.fn() } });
		expect(container.querySelector('button')).toBeNull();
		expect(container.textContent?.trim()).toBe('');
	});
});
