// bits-ui's Select item selects and closes on `pointerup` for every pointer except
// non-iOS touch, which waits for the click. After a tap or a pen, the follow-up click
// then lands on whatever sat under the item — a priority button, a sibling trigger,
// Submit — so swallow it when it misses the item; non-iOS touch's click, landing on the
// item, passes through. A mouse is left alone: its click goes to the element it
// pressed, not to what the closing menu uncovers.
// Never preventDefault the pointerup itself — bits-ui skips its own select on a
// defaultPrevented pointerup.
const GHOST_CLICK_WINDOW_MS = 400;

export function swallowClickThrough(e: PointerEvent): void {
	if (e.pointerType === 'mouse') return;
	const item = e.currentTarget as HTMLElement;
	const swallow = (ev: MouseEvent) => {
		if (item.contains(ev.target as Node)) return;
		ev.preventDefault();
		ev.stopPropagation();
	};
	document.addEventListener('click', swallow, { capture: true, once: true });
	// A tap that produces no ghost click must not leave the listener armed for the
	// user's next real click.
	setTimeout(() => document.removeEventListener('click', swallow, { capture: true }), GHOST_CLICK_WINDOW_MS);
}
