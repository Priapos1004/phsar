import '@testing-library/jest-dom/vitest';
import { vi } from 'vitest';

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
