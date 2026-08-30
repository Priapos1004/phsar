/**
 * Returning to the item you clicked.
 *
 * A detail page's back button is a forward `<a href>` reconstructed from URL
 * params, so the browser's own scroll restoration can never fire — it runs on
 * popstate only. Instead the clicked item's uuid travels back on that href as
 * `?focus=`, and the list page scrolls that item into view.
 *
 * The detail page IS the item that was clicked, so its own `uuid` is the
 * default anchor and no list has to build a focus-carrying link. A `focus`
 * already on the URL wins, which is what makes a deep dive work: after search →
 * anime → media, the back link still names the anime card, the only one present
 * in an anime-view result set.
 *
 * Scroll state is app-owned and keyed on the URL for the same reason the filter
 * stash is — `utils/filterLifecycle` argues why SvelteKit's `snapshot` doesn't
 * fit either of them.
 *
 * The arithmetic is split from the DOM work because jsdom has no layout: the
 * centring itself is only verifiable in a browser.
 */
import { replaceState } from '$app/navigation';

export const FOCUS_PARAM = 'focus';

/** Defined in `app.css`, not as a utility string: it is added from here, where
 *  Tailwind's class scanner cannot see it. The class and the keyframes share the
 *  name, so this identifies both the marker and the animation to wait on. */
const FLASH_CLASS = 'focus-flash';

/** How long the target is held centred while the page finishes settling — see
 *  `revealFocused` for what arrives late. Long enough to outlast it, short enough
 *  that nobody has settled into reading yet. */
const PIN_MS = 600;

/**
 * `base` carrying the focus uuid, or `base` alone.
 *
 * Back-link targets are hand-built strings, several of which already carry a query,
 * so the separator is decided here rather than at each branch. Everything that
 * writes or reads the param goes through `FOCUS_PARAM`, so renaming it is one edit.
 */
export function hrefWithFocus(base: string, uuid: string | null | undefined): string {
	if (!uuid) return base;
	return `${base}${base.includes('?') ? '&' : '?'}${FOCUS_PARAM}=${encodeURIComponent(uuid)}`;
}

/**
 * How far a "Show More" list must be expanded to render `index`.
 *
 * Floored at `current` so a return never *shrinks* a list the user had already
 * expanded past the item they clicked.
 */
export function pageCovering(index: number, pageSize: number, current: number): number {
	return Math.max(current, (Math.floor(index / pageSize) + 1) * pageSize);
}

/**
 * Centre the element tagged `data-focus-uuid={uuid}`, hold it there while the page
 * settles, and flash it.
 *
 * A single scroll is not enough, because the list keeps moving after it. Content
 * landing after first paint re-wraps a card title; equal-height grid rows then
 * carry that height into every row, so a target near the end of a long list drifts
 * down by the growth of every row above it. The same navigation also has to survive
 * SvelteKit's own post-navigation `scrollTo(0, 0)`, which runs on a microtask after
 * mount and so only collides where the page's data was already cached.
 *
 * Both are absorbed by holding the target centred rather than by predicting when
 * the page will be still. Re-centring each frame follows growth as it happens,
 * which reads as the page settling around the card; scrolling once and correcting
 * afterwards puts the same displacement into a single visible lurch.
 *
 * The lookup waits for a frame with it, so a uuid that matches nothing rendered —
 * filtered out, a grain switch, a stale link — leaves the page where it is.
 */
export function revealFocused(uuid: string | null): void {
	if (!uuid) return;
	requestAnimationFrame(() => {
		const el = document.querySelector<HTMLElement>(`[data-focus-uuid="${CSS.escape(uuid)}"]`);
		if (!el) return;
		flash(el);
		pinCentred(el);
	});
}

/** Mark `el`, and unmark it when the animation says so rather than on a timer here —
 *  the class has to go for a later return to replay it, and a duration duplicated in
 *  this file would drift from the one in `app.css`. A table row runs the sweep
 *  alongside, so the name is what distinguishes the end of the flash from the end of
 *  the highlight crossing it. */
function flash(el: HTMLElement): void {
	el.classList.add(FLASH_CLASS);
	const done = (event: AnimationEvent) => {
		if (event.animationName !== FLASH_CLASS) return;
		el.classList.remove(FLASH_CLASS);
		el.removeEventListener('animationend', done);
	};
	el.addEventListener('animationend', done);
}

/** Keep `el` centred until the page has stopped moving under it, then let go. */
function pinCentred(el: HTMLElement): void {
	const until = Date.now() + PIN_MS;
	el.scrollIntoView({ block: 'center' });
	// Where the last centring left the page. A scroll position that is no longer it
	// means the user has taken over, and following them would be a fight they cannot
	// win.
	let anchor = window.scrollY;
	const pin = () => {
		if (window.scrollY !== anchor) return;
		el.scrollIntoView({ block: 'center' });
		anchor = window.scrollY;
		if (Date.now() < until) requestAnimationFrame(pin);
	};
	requestAnimationFrame(pin);
}

/**
 * The focus uuid on `url`, with the param stripped from the address bar.
 *
 * Stripping is what stops a refresh from re-scrolling: this is a one-shot
 * instruction from a back link, not state the page should keep. It is cosmetic,
 * so a `replaceState` the router refuses must not cost the scroll it was
 * tidying up after.
 */
export function consumeFocus(url: URL): string | null {
	const uuid = url.searchParams.get(FOCUS_PARAM);
	if (!uuid) return null;
	const stripped = new URL(url);
	stripped.searchParams.delete(FOCUS_PARAM);
	try {
		replaceState(`${stripped.pathname}${stripped.search}`, {});
	} catch {
		// See above — the scroll is the feature, the tidy URL is not.
	}
	return uuid;
}
