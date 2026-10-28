// Pins `SeeAllResults`' `pending` contract.
import { describe, it, expect } from 'vitest';
import { render, screen, fireEvent } from '@testing-library/svelte';
import SeeAllResults from '$lib/components/SeeAllResults.svelte';
import type { AnimeSearchResult } from '$lib/types/api';
import { SEE_ALL_STEP } from '$lib/utils/search';

const list = (n: number) => Array.from({ length: n }, (_, i) => (
	{ uuid: `u${i}`, title: `T${i}`, name_eng: null, name_jap: null, media_types: [] } as unknown as AnimeSearchResult
));
const tiles = (container: HTMLElement) => container.querySelectorAll('[data-focus-uuid]').length;

const props = {
	back: {}, title: 'All results', grain: 'anime' as const, params: { query: '', search_type: 'title' as const },
	limit: 1000, isGuest: false,
	tileHref: (uuid: string) => `/anime?uuid=${uuid}`,
};

describe('SeeAllResults while the rest loads', () => {
	it('keeps a Show More clicked before the rest arrived', async () => {
		const { container, rerender } = render(SeeAllResults, {
			props: { ...props, rows: list(SEE_ALL_STEP), pending: true },
		});
		expect(screen.getByText(`${SEE_ALL_STEP}+ anime`)).toBeInTheDocument();

		await fireEvent.click(screen.getByRole('button', { name: 'Show More' }));
		expect(screen.getByRole('button', { name: 'Loading…' })).toBeDisabled();

		await rerender({ rows: list(300), pending: false });
		expect(tiles(container)).toBe(2 * SEE_ALL_STEP);
		expect(screen.getByRole('button', { name: 'Show More' })).toBeEnabled();
	});

	it('starts a new list at the first step', async () => {
		const { container, rerender } = render(SeeAllResults, { props: { ...props, rows: list(300) } });
		await fireEvent.click(screen.getByRole('button', { name: 'Show More' }));
		expect(tiles(container)).toBe(2 * SEE_ALL_STEP);

		await rerender({ rows: null });
		await rerender({ rows: list(300) });
		expect(tiles(container)).toBe(SEE_ALL_STEP);
	});
});
