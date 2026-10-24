import { describe, it, expect, vi } from 'vitest';
import { render, screen, fireEvent } from '@testing-library/svelte';
import AttributeSelect from '$lib/components/AttributeSelect.svelte';

describe('AttributeSelect', () => {
	// Guards a dialog's jump to the top; the why is on AttributeSelect's ✕.
	it('clears into the trigger, not into a removed button', async () => {
		const onChange = vi.fn();
		render(AttributeSelect, {
			props: { label: 'Pace', options: [{ value: 'slow', label: 'Slow' }], value: 'slow', onChange },
		});
		const clear = screen.getByRole('button', { name: 'Clear Pace' });
		clear.focus();

		await fireEvent.click(clear);

		expect(onChange).toHaveBeenCalledWith(null);
		expect(document.activeElement?.getAttribute('data-slot')).toBe('select-trigger');
	});
});
