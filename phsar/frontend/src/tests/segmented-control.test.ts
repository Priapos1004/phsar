import { describe, it, expect, vi } from 'vitest';
import { render, screen, fireEvent } from '@testing-library/svelte';
import SegmentedControl from '$lib/components/SegmentedControl.svelte';

const OPTIONS = [
	{ value: 'genres', label: 'Genres' },
	{ value: 'studios', label: 'Studios' },
];

describe('SegmentedControl', () => {
	it('renders one button per option', () => {
		render(SegmentedControl, { props: { options: OPTIONS, value: 'genres', onSelect: () => {} } });
		expect(screen.getByText('Genres')).toBeInTheDocument();
		expect(screen.getByText('Studios')).toBeInTheDocument();
	});

	it('marks the active option with the solid-primary thumb', () => {
		render(SegmentedControl, { props: { options: OPTIONS, value: 'studios', onSelect: () => {} } });
		expect(screen.getByText('Studios').className).toContain('bg-primary');
		expect(screen.getByText('Genres').className).not.toContain('bg-primary');
	});

	it('fires onSelect with the clicked option value', async () => {
		const onSelect = vi.fn();
		render(SegmentedControl, { props: { options: OPTIONS, value: 'genres', onSelect } });
		await fireEvent.click(screen.getByText('Studios'));
		expect(onSelect).toHaveBeenCalledWith('studios');
	});

	it('supports numeric option values', async () => {
		const onSelect = vi.fn();
		render(SegmentedControl, {
			props: { options: [{ value: 5, label: '5' }, { value: 10, label: '10' }], value: 5, onSelect },
		});
		await fireEvent.click(screen.getByText('10'));
		expect(onSelect).toHaveBeenCalledWith(10);
	});
});
