import { describe, it, expect, vi } from 'vitest';
import { render, screen } from '@testing-library/svelte';
import BackLink from '$lib/components/BackLink.svelte';
import MediaInfo from '$lib/components/MediaInfo.svelte';
import { goto } from '$app/navigation';
import {
	absoluteDetailUrl,
	buildDetailHref,
	detailOrigin,
	navigateToSearch,
	searchBySource,
	searchByStudio,
} from '$lib/utils/navigation';
import { api } from '$lib/api';

// `goto` is globally mocked in setup.ts; mock the API so navigateToSearch's
// token POST doesn't hit the network.
vi.mock('$lib/api', () => ({
	api: { post: vi.fn().mockResolvedValue({ token: 'tok' }) },
	ApiError: class ApiError extends Error {},
}));

describe('buildDetailHref', () => {
	const uuid = 'abc-123';

	it('renders just the uuid when no opts are passed', () => {
		expect(buildDetailHref('anime', uuid)).toBe(`/anime?uuid=${uuid}`);
	});

	it('propagates a search token as ?q=', () => {
		expect(buildDetailHref('media', uuid, { q: 'token-xyz' })).toBe(
			`/media?uuid=${uuid}&q=token-xyz`,
		);
	});

	it('propagates an origin marker as ?from=', () => {
		expect(buildDetailHref('anime', uuid, { from: 'library' })).toBe(
			`/anime?uuid=${uuid}&from=library`,
		);
	});

	it('emits both ?q= and ?from= when present', () => {
		expect(buildDetailHref('media', uuid, { q: 'tok', from: 'library' })).toBe(
			`/media?uuid=${uuid}&q=tok&from=library`,
		);
	});

	it('skips nullish opts so detail pages do not get ?q=null', () => {
		expect(buildDetailHref('anime', uuid, { q: null, from: null })).toBe(
			`/anime?uuid=${uuid}`,
		);
	});

	it('percent-encodes tokens with URL-unsafe characters', () => {
		const href = buildDetailHref('media', uuid, { q: 'a b/c?d' });
		expect(href).toContain('q=a+b%2Fc%3Fd');
	});

	it('propagates the scroll anchor as ?focus=', () => {
		expect(buildDetailHref('media', uuid, { focus: 'anime-1' })).toBe(
			`/media?uuid=${uuid}&focus=anime-1`,
		);
	});

	it('carries the carousel a see-all tile was opened from', () => {
		expect(buildDetailHref('anime', uuid, { from: 'carousel', carousel: 'fresh' })).toBe(
			`/anime?uuid=${uuid}&from=carousel&carousel=fresh`,
		);
	});
});

describe('detailOrigin', () => {
	const at = (href: string) => detailOrigin(new URL(href, 'https://example.test'));

	it('anchors on the page itself when no hop named a focus', () => {
		expect(at('/anime?uuid=a1&from=carousel&carousel=fresh')).toEqual({
			q: null, from: 'carousel', job: null, carousel: 'fresh', focus: 'a1',
		});
	});

	it('keeps a focus a deeper hop already named', () => {
		expect(at('/media?uuid=m1&from=watchlist&focus=a1').focus).toBe('a1');
	});

	// A see-all → anime → media dive still links back to the see-all, at the anime tile.
	it('survives an anime → media hop whole', () => {
		const animePage = at('/anime?uuid=a1&from=carousel&carousel=fresh');
		const mediaPage = at(buildDetailHref('media', 'm1', animePage));
		expect(mediaPage).toEqual({ ...animePage });
	});
});

describe('navigateToSearch', () => {
	it('lands on the path it is given', async () => {
		await navigateToSearch({ query: 'frieren', search_type: 'title' }, '/search/all');
		expect(goto).toHaveBeenCalledWith('/search/all?q=tok');
	});

	// The default search runs without a token, so a search asking for nothing
	// (`isDefaultSearch`) mints none.
	it('goes bare to a search that asks for nothing', async () => {
		vi.mocked(api.post).mockClear();
		await navigateToSearch({ query: ' ', search_type: 'title', view_type: 'anime', studio_mode: 'any', genres: null });
		expect(goto).toHaveBeenCalledWith('/search');
		expect(api.post).not.toHaveBeenCalled();
		await navigateToSearch({ query: '', search_type: 'title', view_type: 'anime', sort: 'top_rated' });
		expect(api.post).not.toHaveBeenCalled();
		await navigateToSearch({ query: '', search_type: 'title', view_type: 'anime', sort: 'top_rated', sort_dir: 'asc' });
		await navigateToSearch({ query: '', search_type: 'title', view_type: 'anime', sort: 'random' });
		expect(api.post).toHaveBeenCalledTimes(2);
	});
});

describe('absoluteDetailUrl', () => {
	// A share link records nothing about how the sharer got there — the scroll
	// anchor would send a recipient back to a list they never saw.
	it('stays bare', () => {
		expect(absoluteDetailUrl('anime', 'abc-123', 'https://example.test')).toBe(
			'https://example.test/anime?uuid=abc-123',
		);
	});
});

describe('searchByStudio', () => {
	it('posts an anime-view search filtered to the studio', () => {
		searchByStudio('Wit Studio');
		// navigateToSearch calls api.post synchronously before awaiting the token.
		expect(api.post).toHaveBeenCalledWith(
			'/filters/create-token',
			expect.objectContaining({ studio_name: ['Wit Studio'], view_type: 'anime', search_type: 'title', query: '' }),
		);
	});

	it("adds the caller's scope", () => {
		searchByStudio('Wit Studio', { watchlisted: true });
		expect(api.post).toHaveBeenLastCalledWith(
			'/filters/create-token',
			expect.objectContaining({ studio_name: ['Wit Studio'], watchlisted: true }),
		);
	});
});

describe('searchBySource', () => {
	it('posts an anime-view search filtered to the source', () => {
		searchBySource('Light Novel');
		expect(api.post).toHaveBeenCalledWith(
			'/filters/create-token',
			expect.objectContaining({ original_source: ['Light Novel'], view_type: 'anime', search_type: 'title', query: '' }),
		);
	});
});

describe('BackLink', () => {
	const backLink = (label: string) => screen.getByText(label).closest('a');

	it('returns a browse detail to the tile it was opened from', () => {
		render(BackLink, { props: { origin: { from: 'browse', focus: 'fresh:abc-123' } } });
		expect(backLink('Back to browse')).toHaveAttribute('href', '/browse?focus=fresh%3Aabc-123');
	});

	it('returns a home row\'s detail to home, at the tile', () => {
		render(BackLink, { props: { origin: { from: 'home', focus: 'lucky-find:abc-123' } } });
		expect(backLink('Back to home')).toHaveAttribute('href', '/?focus=lucky-find%3Aabc-123');
	});

	it('returns a see-all detail to its carousel, at the tile', () => {
		render(BackLink, { props: { origin: { from: 'carousel', carousel: 'fresh', focus: 'abc-123' } } });
		expect(backLink('Back to the list')).toHaveAttribute('href', '/browse/fresh?focus=abc-123');
	});

	// The token alone would read "Back to search" and land on the capped search.
	it('returns a search see-all detail there rather than to the search', () => {
		render(BackLink, { props: { origin: { from: 'search-all', q: 'tok', focus: 'abc-123' } } });
		expect(backLink('Back to all results')).toHaveAttribute('href', '/search/all?q=tok&focus=abc-123');
	});

	// The default search has no token, so its see-all and its way back carry none.
	it('returns a default search see-all detail there without a token', () => {
		render(BackLink, { props: { origin: { from: 'search-all', focus: 'abc-123' } } });
		expect(backLink('Back to all results')).toHaveAttribute('href', '/search/all?focus=abc-123');
	});

	it('returns a default search result there, at its card', () => {
		render(MediaInfo, { props: { info_type: 'anime', title: 'T', airing_status: 'Finished Airing', media_uuid: 'abc-123' } });
		const detail = screen.getByRole('link', { name: /T/ }).getAttribute('href')!;
		render(BackLink, { props: { origin: detailOrigin(new URL(detail, 'http://x')) } });
		expect(backLink('Back to search')).toHaveAttribute('href', '/search?focus=abc-123');
	});

	it('returns a see-all without a token to the default search', () => {
		render(BackLink, { props: { origin: { from: 'search' } } });
		expect(backLink('Back to search')).toHaveAttribute('href', '/search');
	});
});
