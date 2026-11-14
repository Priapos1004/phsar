import { describe, it, expect, vi, afterEach } from 'vitest';
import { render, screen, fireEvent, within } from '@testing-library/svelte';
import { page } from '$app/state';
import { api } from '$lib/api';
import { userSettings } from '$lib/stores/userSettings';
import RecommendationSettings from '../lib/components/RecommendationSettings.svelte';
import SettingsPage from '../routes/settings/+page.svelte';
import type { HistoryStart, HistoryStartRating, UserSettings } from '../lib/types/api';

const SETTINGS: UserSettings = {
	theme: 'default', name_language: 'english', default_search_view: 'anime', rating_step: '0.5',
	spoiler_level: 'off', recommend_hot: true,
};

const rating = (uuid: string, title: string, at: string): HistoryStartRating => (
	{ uuid, title, name_eng: null, name_jap: null, cover_image: null, at }
);

// Oldest first, as the endpoint sends them. Midday UTC, so each day reads the same in every
// zone the suite might run in.
const START: HistoryStart = {
	detected: 'b',
	chosen: null,
	ratings: [
		rating('a', 'Imported Show', '2026-03-03T12:00:00Z'),
		rating('b', 'First Natural', '2026-03-04T12:00:00Z'),
		rating('c', 'Latest Watch', '2026-03-05T12:00:00Z'),
	],
};

const setUrl = (url: string) => ((page as { url: URL }).url = new URL(url));
const row = (uuid: string) => document.querySelector<HTMLElement>(`[data-uuid="${uuid}"]`)!;
const dimmed = (uuid: string) => row(uuid).querySelector('.opacity-50') !== null;

afterEach(() => {
	vi.restoreAllMocks();
	setUrl('http://localhost:5173');
});

/** The card over `start`; the PUT answers with `chosen` moved, as the endpoint does. */
function renderCard(start: HistoryStart, { isRestricted = false, settings = SETTINGS } = {}) {
	const get = vi.spyOn(api, 'get').mockResolvedValue(start);
	const put = vi.spyOn(api, 'put').mockImplementation(async (_path, body) => (
		{ ...start, chosen: (body as { rating: string | null }).rating }
	));
	render(RecommendationSettings, { settings, isRestricted, onSave: vi.fn() });
	return { get, put };
}

const change = () => fireEvent.click(screen.getByRole('button', { name: /Change|Close/ }));

describe('RecommendationSettings', () => {
	it('shows the detected start, and lists the ratings newest first once opened', async () => {
		renderCard(START);
		expect(await screen.findByText('Mar 4, 2026 · detected')).toBeTruthy();
		expect(document.querySelector('[data-uuid]')).toBeNull();
		await change();
		const order = [...document.querySelectorAll('[data-uuid]')].map((el) => el.getAttribute('data-uuid'));
		expect(order).toEqual(['c', 'b', 'a']);
	});

	it('dims what is older than the start, and follows a new pick', async () => {
		const { put } = renderCard(START);
		await screen.findByText('Mar 4, 2026 · detected');
		await change();
		expect([dimmed('c'), dimmed('b'), dimmed('a')]).toEqual([false, false, true]);
		await fireEvent.click(within(row('c')).getByRole('button', { name: 'Start here' }));
		expect(put).toHaveBeenCalledWith('/ratings/history-start', { rating: 'c' });
		expect(await screen.findByText('Mar 5, 2026 · your pick')).toBeTruthy();
		await change();
		expect([dimmed('c'), dimmed('b'), dimmed('a')]).toEqual([false, true, true]);
	});

	it('clears the pick when the detected rating is picked', async () => {
		const { put } = renderCard({ ...START, chosen: 'a' });
		await screen.findByText('Mar 3, 2026 · your pick');
		await change();
		await fireEvent.click(within(row('b')).getByRole('button', { name: 'Start here' }));
		expect(put).toHaveBeenCalledWith('/ratings/history-start', { rating: null });
		expect(await screen.findByText('Mar 4, 2026 · detected')).toBeTruthy();
	});

	it('reads a stored pick of the detected rating as detected', async () => {
		renderCard({ ...START, chosen: 'b' });
		expect(await screen.findByText('Mar 4, 2026 · detected')).toBeTruthy();
		expect(screen.queryByRole('button', { name: 'Use detected' })).toBeNull();
	});

	it('clears a chosen start with Use detected', async () => {
		const { put } = renderCard({ ...START, chosen: 'a' });
		await fireEvent.click(await screen.findByRole('button', { name: 'Use detected' }));
		expect(put).toHaveBeenCalledWith('/ratings/history-start', { rating: null });
		expect(await screen.findByText('Mar 4, 2026 · detected')).toBeTruthy();
	});

	it('names each rating in the user\'s name language', async () => {
		const named = { ...START, ratings: START.ratings.map((r) => ({ ...r, name_jap: `${r.title} (jp)` })) };
		renderCard(named, { settings: { ...SETTINGS, name_language: 'japanese' } });
		expect(await screen.findByText('First Natural (jp)')).toBeTruthy();
	});

	it('asks a guest for nothing', () => {
		const { get } = renderCard(START, { isRestricted: true });
		expect(get).not.toHaveBeenCalled();
		expect(screen.getByText('Guest accounts get no recommendations')).toBeTruthy();
	});
});

describe('the settings page', () => {
	it('opens the tab ?tab= names, and General otherwise', () => {
		userSettings.set(SETTINGS);
		vi.spyOn(api, 'get').mockResolvedValue(START);
		const context = new Map([['userRole', () => 'user']]);
		setUrl('http://localhost:5173/settings?tab=recommendations');
		const first = render(SettingsPage, { context });
		expect(screen.getByRole('heading', { name: 'Recommendations' })).toBeTruthy();
		expect(screen.queryByRole('heading', { name: 'Theme' })).toBeNull();
		first.unmount();
		setUrl('http://localhost:5173/settings');
		render(SettingsPage, { context });
		expect(screen.getByRole('heading', { name: 'Theme' })).toBeTruthy();
		expect(screen.queryByRole('heading', { name: 'Recommendations' })).toBeNull();
	});
});
