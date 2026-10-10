// On iOS, bits-ui's Select item selects and closes on `pointerup` (its non-iOS touch
// path waits for the click instead), so the browser's follow-up click lands on
// whatever sat under the item — a priority button, a sibling trigger, Submit. Swallow
// that one click when it misses the item. The target check is what keeps Android
// safe: there bits-ui waits for the click on the item itself, which passes through.
// Never preventDefault the pointerup itself — bits-ui skips its own select on a
// defaultPrevented pointerup.
const GHOST_CLICK_WINDOW_MS = 400;

export function swallowClickThrough(e: PointerEvent): void {
	if (e.pointerType !== 'touch') return;
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
