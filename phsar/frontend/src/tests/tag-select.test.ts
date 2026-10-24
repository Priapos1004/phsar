import { describe, it, expect, vi } from 'vitest';
import { render, screen, fireEvent } from '@testing-library/svelte';
import TagSelect from '$lib/components/TagSelect.svelte';

describe('TagSelect', () => {
	// Guards the sheet's jump to the top; the why is on TagSelect's option mousedown.
	it('picks an option without moving focus off the input', async () => {
		const onAdd = vi.fn();
		render(TagSelect, { props: { options: ['Action', 'Drama'], onAdd, onRemove: vi.fn() } });
		await fireEvent.focus(screen.getByRole('textbox'));

		const notCancelled = await fireEvent.mouseDown(screen.getByRole('button', { name: 'Action' }));

		expect(notCancelled).toBe(false);
		expect(onAdd).toHaveBeenCalledWith('Action');
	});

	// Guards closing on focus leaving the picker; the why is on TagSelect's root.
	it('stays open while focus moves inside the picker, closes when it leaves', async () => {
		render(TagSelect, { props: { options: ['Action', 'Drama'], onAdd: vi.fn(), onRemove: vi.fn() } });
		const input = screen.getByRole('textbox');
		await fireEvent.focus(input);
		const box = input.closest('[role="button"]')!;

		await fireEvent.focusOut(input, { relatedTarget: box });
		// Longer than any blur timer would wait, so closing on one fails here.
		await new Promise((resolve) => setTimeout(resolve, 200));
		expect(screen.getByRole('button', { name: 'Action' })).toBeInTheDocument();

		await fireEvent.focusOut(box, { relatedTarget: document.body });
		expect(screen.queryByRole('button', { name: 'Action' })).not.toBeInTheDocument();
	});
});
