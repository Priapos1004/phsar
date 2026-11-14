import { describe, expect, it, vi } from 'vitest';
import { fireEvent, render, screen } from '@testing-library/svelte';
import { createRawSnippet } from 'svelte';
import Tooltip from '$lib/components/Tooltip.svelte';
import TooltipLinkTest from './TooltipLinkTest.svelte';

const label = createRawSnippet(() => ({ render: () => '<span>Label</span>' }));
const trigger = () => screen.getByText('Label').parentElement!;

// A whole tap, not just the pointerup: bits-ui closes on pointerdown and click unless the
// Root disables it, so a test firing pointerup alone would pass without that half. Answers
// whether the click went unprevented, so a link around the trigger would follow it.
async function tap(pointerType: string, target = trigger()) {
	await fireEvent.pointerDown(target, { pointerType });
	await fireEvent.pointerUp(target, { pointerType });
	return fireEvent.click(target);
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

describe('Tooltip, inside a link', () => {
	it('with insideLink, a touch tap opens it and holds the link, and a mouse click follows it', async () => {
		render(TooltipLinkTest, { insideLink: true });

		expect(await tap('touch')).toBe(false);
		await vi.waitFor(() => expect(isOpen()).toBe(true));
		expect(await tap('mouse')).toBe(true);
	});

	it('without it, a touch tap follows the link', async () => {
		render(TooltipLinkTest, {});

		expect(await tap('touch')).toBe(true);
	});

	it('a trigger-mode button still acts on a touch tap, insideLink or not', async () => {
		const onact = vi.fn();
		render(TooltipLinkTest, { insideLink: true, onact });

		expect(await tap('touch', screen.getByRole('button', { name: 'Act' }))).toBe(true);
		expect(onact).toHaveBeenCalledOnce();
	});
});
