// jsdom lays nothing out, so the measurements are stubbed: this pins `hugLines`' arithmetic,
// not what a browser renders.
import { afterEach, describe, expect, it, vi } from 'vitest';
import { hugLines } from '$lib/utils/hugLines';

afterEach(() => vi.restoreAllMocks());

describe('hugLines', () => {
	it('fits a bubble mid zoom-in to its widest line, never a fraction short of it', () => {
		// A label over a one-line sentence 150.4px wide, measured at 95% while the bubble zooms
		// in. The box's laid-out width is the sentence's, and `offsetWidth` rounds it down.
		const node = document.createElement('div');
		node.innerHTML = '<p>Continuation</p><p>Pick up where you left off</p>';
		document.body.append(node);
		const scale = 0.95;
		vi.spyOn(Range.prototype, 'getClientRects')
			.mockReturnValueOnce([{ top: 0, left: 0, right: scale * 80 }] as unknown as DOMRectList)
			.mockReturnValueOnce([{ top: 15, left: 0, right: scale * 150.4 }] as unknown as DOMRectList);
		vi.spyOn(node, 'getBoundingClientRect').mockReturnValue({ width: scale * 150.4 } as DOMRect);
		Object.defineProperty(node, 'offsetWidth', { value: 150 });
		vi.spyOn(globalThis, 'getComputedStyle').mockReturnValue({
			width: '150.4px', paddingLeft: '0', paddingRight: '0', borderLeftWidth: '0', borderRightWidth: '0',
		} as CSSStyleDeclaration);

		const stop = hugLines(node);
		expect(node.style.width).toBe('151px');
		stop?.();
		node.remove();
	});
});
