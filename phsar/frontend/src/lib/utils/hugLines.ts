import type { Attachment } from 'svelte/attachments';

/** Sizes a box whose text wraps to its widest line. CSS sizes it to the width available,
 * never to the lines its text ends with, so a wrapped chip would keep the empty space its
 * last line left — beside a centred text, on both sides. Text that fits on one line keeps
 * its own width. The text nodes alone are measured, since an inline-block holding wrapped
 * text spans the whole width itself.
 *
 * Re-fits when the page's width changes (a window resize, a scrollbar appearing) or the
 * text does. Not on the box's own parent: that resizes with the box, so watching it would
 * answer every fit with another. */
export const hugLines: Attachment<HTMLElement> = (node) => {
	const range = document.createRange();
	const fit = () => {
		node.style.width = '';
		const rects: DOMRect[] = [];
		const walker = document.createTreeWalker(node, NodeFilter.SHOW_TEXT);
		for (let text = walker.nextNode(); text; text = walker.nextNode()) {
			range.selectNodeContents(text);
			rects.push(...range.getClientRects());
		}
		if (new Set(rects.map((r) => Math.round(r.top))).size < 2) return;
		const style = getComputedStyle(node);
		const frame = parseFloat(style.paddingLeft) + parseFloat(style.paddingRight)
			+ parseFloat(style.borderLeftWidth) + parseFloat(style.borderRightWidth);
		const widest = Math.max(...rects.map((r) => r.right)) - Math.min(...rects.map((r) => r.left));
		node.style.width = `${Math.ceil(widest + frame)}px`;
	};
	fit();
	const edits = new MutationObserver(fit);
	edits.observe(node, { characterData: true, childList: true, subtree: true });
	// Width alone: the page's height changes with every result that loads.
	let pageWidth = document.documentElement.clientWidth;
	const page = new ResizeObserver(() => {
		const width = document.documentElement.clientWidth;
		if (width !== pageWidth) {
			pageWidth = width;
			fit();
		}
	});
	page.observe(document.documentElement);
	return () => {
		edits.disconnect();
		page.disconnect();
	};
};
