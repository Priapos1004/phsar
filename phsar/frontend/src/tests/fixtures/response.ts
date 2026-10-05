/** Minimal `Response` stand-in for `globalThis.fetch` mocks.
 *
 * Here rather than per-file: the component tests that mock fetch all need the same
 * three fields, and the first one to read `headers`, `text()` or `statusText` off a
 * mocked response should have one place to add it.
 */
export function jsonResponse(body: unknown, status = 200): Response {
	return {
		ok: status >= 200 && status < 300,
		status,
		json: () => Promise.resolve(body),
	} as Response;
}
