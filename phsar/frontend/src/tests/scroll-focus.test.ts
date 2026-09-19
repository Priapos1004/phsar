import { describe, it, expect, vi, beforeEach, afterEach } from 'vitest';
import { replaceState } from '$app/navigation';
import { consumeFocus, hrefWithFocus, pageCovering, revealFocused } from '$lib/utils/scrollFocus';

describe('hrefWithFocus', () => {
	it('opens a query string on a bare path', () => {
		expect(hrefWithFocus('/ratings', 'abc')).toBe('/ratings?focus=abc');
	});

	it('appends to a base that already carries one', () => {
		expect(hrefWithFocus('/admin?tab=jobs', 'abc')).toBe('/admin?tab=jobs&focus=abc');
	});

	it('returns the base untouched without a uuid', () => {
		expect(hrefWithFocus('/watchlist', null)).toBe('/watchlist');
		expect(hrefWithFocus('/watchlist', undefined)).toBe('/watchlist');
	});

	it('percent-encodes the uuid', () => {
		expect(hrefWithFocus('/search', 'a b&c')).toBe('/search?focus=a%20b%26c');
	});
});

describe('pageCovering', () => {
	it('expands to the page holding the index', () => {
		expect(pageCovering(0, 20, 20)).toBe(20);
		expect(pageCovering(19, 20, 20)).toBe(20);
		expect(pageCovering(20, 20, 20)).toBe(40);
		expect(pageCovering(84, 20, 20)).toBe(100);
	});

	it('never shrinks a list the user already expanded', () => {
		expect(pageCovering(3, 20, 200)).toBe(200);
	});
});

describe('consumeFocus', () => {
	beforeEach(() => vi.mocked(replaceState).mockClear());

	it('returns the uuid and strips the param, keeping the rest of the query', () => {
		const url = new URL('http://x/search?q=tok&focus=abc');
		expect(consumeFocus(url)).toBe('abc');
		expect(replaceState).toHaveBeenCalledWith('/search?q=tok', {});
	});

	it('drops the query string entirely when focus was the only param', () => {
		expect(consumeFocus(new URL('http://x/ratings?focus=abc'))).toBe('abc');
		expect(replaceState).toHaveBeenCalledWith('/ratings', {});
	});

	it('leaves the URL alone when there is nothing to consume', () => {
		expect(consumeFocus(new URL('http://x/ratings'))).toBeNull();
		expect(replaceState).not.toHaveBeenCalled();
	});

	it('still returns the uuid when the router refuses the strip', () => {
		vi.mocked(replaceState).mockImplementationOnce(() => {
			throw new Error('Cannot call replaceState(...) before router is initialized');
		});
		expect(consumeFocus(new URL('http://x/ratings?focus=abc'))).toBe('abc');
	});
});

describe('revealFocused', () => {
	// jsdom lays nothing out and scrolls nothing, so the centring itself is not
	// observable here — only which node is picked, when it is touched, and how long
	// the pin keeps hold of it.
	const scrollIntoView = vi.fn();

	const frame = () => new Promise<void>((resolve) => requestAnimationFrame(() => resolve()));
	const frames = async (n: number) => {
		for (let i = 0; i < n; i++) await frame();
	};

	/** The mock never moves the page, so the pin reads its own centring back as
	 *  unchanged — which is what "the user has not taken over" looks like. */
	const userScrollsTo = (y: number) =>
		Object.defineProperty(window, 'scrollY', { value: y, configurable: true });

	beforeEach(() => {
		scrollIntoView.mockClear();
		Element.prototype.scrollIntoView = scrollIntoView;
		userScrollsTo(0);
		document.body.innerHTML = `
			<a data-focus-uuid="one">1</a>
			<a data-focus-uuid="two">2</a>`;
	});

	afterEach(async () => {
		// Hand over to "the user" so a pin still holding cannot reach into the next
		// test — it outlives any single one by design.
		userScrollsTo(999);
		await frame();
		document.body.innerHTML = '';
		userScrollsTo(0);
	});

	it('centres and flashes the matching node', async () => {
		revealFocused('two');
		await frames(2);
		expect(scrollIntoView).toHaveBeenCalledWith({ block: 'center' });
		expect(document.querySelector('[data-focus-uuid="two"]')).toHaveClass('focus-flash');
		expect(document.querySelector('[data-focus-uuid="one"]')).not.toHaveClass('focus-flash');
	});

	it('touches nothing synchronously', () => {
		revealFocused('two');
		expect(scrollIntoView).not.toHaveBeenCalled();
	});

	// The node is looked up a frame in, so a caller that reveals more rows in the
	// same flush gets the row it just rendered rather than a miss.
	it('finds a node that appears while it waits', async () => {
		revealFocused('three');
		document.body.insertAdjacentHTML('beforeend', '<a data-focus-uuid="three">3</a>');
		await frames(2);
		expect(document.querySelector('[data-focus-uuid="three"]')).toHaveClass('focus-flash');
	});

	it('leaves the page alone on a miss, so a stale uuid lands at the top', async () => {
		revealFocused('gone');
		revealFocused(null);
		await frames(3);
		expect(scrollIntoView).not.toHaveBeenCalled();
	});

	// The list keeps growing after the first scroll — content landing late re-wraps a
	// card and equal-height rows carry it into every row above the target. Holding is
	// what absorbs that; one scroll would strand the target below the fold.
	it('keeps re-centring while the page is still settling', async () => {
		revealFocused('two');
		await frames(2);
		const early = scrollIntoView.mock.calls.length;
		await frames(3);
		expect(scrollIntoView.mock.calls.length).toBeGreaterThan(early);
	});

	it('lets go once the user scrolls', async () => {
		revealFocused('two');
		await frames(2);
		userScrollsTo(420);
		await frame();
		const afterHandover = scrollIntoView.mock.calls.length;
		await frames(4);
		expect(scrollIntoView.mock.calls.length).toBe(afterHandover);
	});

	it('lets go on its own once the window closes', async () => {
		revealFocused('two');
		await new Promise((resolve) => setTimeout(resolve, 800));
		const settledCount = scrollIntoView.mock.calls.length;
		await frames(4);
		expect(scrollIntoView.mock.calls.length).toBe(settledCount);
	});
});
