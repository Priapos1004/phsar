import { describe, expect, it, vi } from 'vitest';
import { fireEvent, render, screen } from '@testing-library/svelte';
import { createRawSnippet } from 'svelte';
import Tooltip from '$lib/components/Tooltip.svelte';

const label = createRawSnippet(() => ({ render: () => '<span>Label</span>' }));
const trigger = () => screen.getByText('Label').parentElement!;

// A whole tap, not just the pointerup: bits-ui closes on pointerdown and click unless the
// Root disables it, so a test firing pointerup alone would pass without that half.
async function tap(pointerType: string) {
	await fireEvent.pointerDown(trigger(), { pointerType });
	await fireEvent.pointerUp(trigger(), { pointerType });
	await fireEvent.click(trigger());
}

const isOpen = () => screen.queryAllByText('The definition').length > 0;

describe('Tooltip, children mode', () => {
	it('a touch tap opens it and the next one closes it', async () => {
		render(Tooltip, { text: 'The definition', children: label });

		await tap('touch');
		await vi.waitFor(() => expect(isOpen()).toBe(true));

		await tap('touch');
		await vi.waitFor(() => expect(isOpen()).toBe(false));
	});

	it('stays open when the lifted finger leaves the trigger', async () => {
		render(Tooltip, { text: 'The definition', children: label });

		await tap('touch');
		await vi.waitFor(() => expect(isOpen()).toBe(true));
		await fireEvent.pointerLeave(trigger(), { pointerType: 'touch' });
		// bits-ui's leave tracking closes a frame later; wait out a few.
		await new Promise((r) => setTimeout(r, 50));
		expect(isOpen()).toBe(true);
	});

	it('a mouse leaving still closes it', async () => {
		render(Tooltip, { text: 'The definition', children: label });

		await tap('touch');
		await vi.waitFor(() => expect(isOpen()).toBe(true));
		await fireEvent.pointerLeave(trigger(), { pointerType: 'mouse' });
		await vi.waitFor(() => expect(isOpen()).toBe(false));
	});

	it('a mouse click leaves it to hover', async () => {
		render(Tooltip, { text: 'The definition', children: label });

		await tap('mouse');
		expect(isOpen()).toBe(false);
	});
});
