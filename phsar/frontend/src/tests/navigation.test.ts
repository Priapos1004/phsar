import { describe, it, expect, vi } from 'vitest';
import { buildDetailHref, searchByStudio } from '$lib/utils/navigation';
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
