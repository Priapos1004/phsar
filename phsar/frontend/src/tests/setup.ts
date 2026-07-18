import '@testing-library/jest-dom/vitest';
import { afterEach, vi } from 'vitest';

// bits-ui's body-scroll-lock (Dialog/Popover) schedules a ~24ms real setTimeout
// to restore <body> styles when a locked component unmounts. If that unmount is
// the last thing a test file does, the timer can fire AFTER jsdom is torn down
// → an uncaught "document is not defined". This afterEach runs after Testing
// Library's auto-unmount (setup files register their hooks earliest and vitest
// runs afterEach LIFO), so when a lock is still pending — `overflow:hidden`
// lingers until the deferred restore — we flush it inside the live-document
// window. No-op for the common no-dialog test, so the wait lands only where a
// dialog actually opened.
afterEach(async () => {
	if (typeof document !== 'undefined' && document.body.style.overflow === 'hidden') {
		await new Promise((resolve) => setTimeout(resolve, 30));
	}
});

// Polyfill Web Animations API for jsdom
if (typeof Element.prototype.animate === 'undefined') {
	Element.prototype.animate = () => ({ cancel: () => {}, finished: Promise.resolve() }) as any;
}

// Mock $app/navigation
vi.mock('$app/navigation', () => ({
	goto: vi.fn(),
	invalidate: vi.fn(),
	invalidateAll: vi.fn(),
	preloadData: vi.fn(),
	preloadCode: vi.fn(),
	beforeNavigate: vi.fn(),
	afterNavigate: vi.fn(),
	onNavigate: vi.fn(),
}));

// Mock $app/environment
vi.mock('$app/environment', () => ({
	browser: true,
	dev: true,
	building: false,
	version: 'test',
}));

// Mock $app/state (Svelte 5)
vi.mock('$app/state', () => ({
	page: {
		url: new URL('http://localhost:5173'),
		params: {},
		route: { id: '/' },
		status: 200,
		error: null,
		data: {},
		form: null,
	},
}));

// Mock $lib/config
vi.mock('$lib/config', () => ({
	API_URL: 'http://localhost:8000',
}));
