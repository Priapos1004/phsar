import { describe, it, expect, vi } from 'vitest';
import { render, screen, fireEvent } from '@testing-library/svelte';
import SearchInput from '../lib/components/SearchInput.svelte';

describe('SearchInput', () => {
	it('empties the box on ✕ and hands focus to it, as the ✕ leaves', async () => {
		const oninput = vi.fn();
		render(SearchInput, { value: 'frieren', placeholder: 'Search…', oninput });
		const clear = screen.getByRole('button', { name: 'Clear search' });
		clear.focus();
		await fireEvent.click(clear);
		const box = screen.getByPlaceholderText('Search…') as HTMLInputElement;
		expect(box.value).toBe('');
		expect(document.activeElement).toBe(box);
		expect(screen.queryByRole('button', { name: 'Clear search' })).toBeNull();
		expect(oninput).toHaveBeenCalledOnce();
	});
});
