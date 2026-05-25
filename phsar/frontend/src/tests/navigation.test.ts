import { describe, it, expect } from 'vitest';
import { buildDetailHref } from '$lib/utils/navigation';

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
