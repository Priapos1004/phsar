import { describe, it, expect } from 'vitest';
import { parseContentDispositionFilename } from '$lib/api';

describe('parseContentDispositionFilename', () => {
	it('returns undefined when header is null', () => {
		expect(parseContentDispositionFilename(null)).toBeUndefined();
	});

	it('returns undefined when header has no filename', () => {
		expect(parseContentDispositionFilename('attachment')).toBeUndefined();
	});

	it('parses quoted filename', () => {
		expect(
			parseContentDispositionFilename('attachment; filename="phsar_export_sam_2026_04_19.json"'),
		).toBe('phsar_export_sam_2026_04_19.json');
	});

	it('parses unquoted filename', () => {
		expect(parseContentDispositionFilename('attachment; filename=backup.dump')).toBe('backup.dump');
	});

	it('is case-insensitive for the filename key', () => {
		expect(parseContentDispositionFilename('ATTACHMENT; FileName="dump.sql"')).toBe('dump.sql');
	});

	it('decodes RFC 5987 UTF-8 percent-encoded filename', () => {
		expect(
			parseContentDispositionFilename("attachment; filename*=UTF-8''caf%C3%A9.csv"),
		).toBe('café.csv');
	});

	it('prefers RFC 5987 filename* over plain filename', () => {
		expect(
			parseContentDispositionFilename(
				"attachment; filename=\"ascii.csv\"; filename*=UTF-8''caf%C3%A9.csv",
			),
		).toBe('café.csv');
	});

	it('falls back to plain filename when RFC 5987 percent-encoding is malformed', () => {
		expect(
			parseContentDispositionFilename(
				"attachment; filename=\"fallback.json\"; filename*=UTF-8''%E0%A4.json",
			),
		).toBe('fallback.json');
	});
});
