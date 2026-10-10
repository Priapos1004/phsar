import { describe, it, expect, vi, beforeEach, afterEach } from 'vitest';
import { swallowClickThrough } from '$lib/utils/clickThrough';

// Covers the listener logic only. Whether a tap really dispatches the ghost click at
// the element under the closed dropdown is a layout fact jsdom can't reproduce —
// that half is checked on a device.
describe('swallowClickThrough', () => {
	let item: HTMLElement;
	let behind: HTMLButtonElement;
	let behindClicked: ReturnType<typeof vi.fn<() => void>>;

	beforeEach(() => {
		vi.useFakeTimers();
		item = document.createElement('div');
		behind = document.createElement('button');
		behindClicked = vi.fn<() => void>();
		behind.addEventListener('click', behindClicked);
		document.body.append(item, behind);
	});

	afterEach(() => {
		vi.runAllTimers();
		vi.useRealTimers();
		item.remove();
		behind.remove();
	});

	function pointerUp(pointerType: string) {
		// jsdom has no PointerEvent constructor; the util only reads the fields stubbed here.
		swallowClickThrough({ pointerType, currentTarget: item } as unknown as PointerEvent);
	}

	it.each(['touch', 'pen'])('swallows the follow-up click that lands behind the item after a %s', (pointerType) => {
		pointerUp(pointerType);
		behind.click();
		expect(behindClicked).not.toHaveBeenCalled();
	});

	it('lets a click on the item itself through (Android selects on that click)', () => {
		const itemClicked = vi.fn();
		item.addEventListener('click', itemClicked);
		pointerUp('touch');
		item.click();
		expect(itemClicked).toHaveBeenCalledOnce();
	});

	it('ignores mouse pointers', () => {
		pointerUp('mouse');
		behind.click();
		expect(behindClicked).toHaveBeenCalledOnce();
	});

	it('disarms when no ghost click arrives, so a later real click goes through', () => {
		pointerUp('touch');
		vi.advanceTimersByTime(500);
		behind.click();
		expect(behindClicked).toHaveBeenCalledOnce();
	});
});
