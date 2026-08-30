import { describe, it, expect, vi } from 'vitest';
import { absoluteDetailUrl, buildDetailHref, searchByStudio } from '$lib/utils/navigation';
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
});
