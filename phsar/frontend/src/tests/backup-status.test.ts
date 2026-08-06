import { describe, it, expect } from 'vitest';
import { compareByRestorability, DUMP_STATUS_ORDER } from '$lib/utils/backupStatus';
import type { BackupMetadata, BackupStatus } from '$lib/types/api';

function dump(status: BackupStatus, over: Partial<BackupMetadata> = {}): BackupMetadata {
	return {
		filename: `phsar-20260727-000000-${status}.dump`,
		size_bytes: 1024,
		created_at: '2026-07-27T00:00:00Z',
		integrity: 'ok',
		source: 'cron',
		status,
		...over,
	};
}

describe('compareByRestorability', () => {
	// The verdict itself is the server's (see utils/backupStatus.ts) — what's
	// tested here is that the sort surfaces the least trustworthy dump first.
	it('orders worst-first, so an intact-but-outdated dump never sorts as healthy', () => {
		const rows: BackupMetadata[] = [dump('ok'), dump('outdated'), dump('corrupt'), dump('unknown')];
		expect([...rows].sort(compareByRestorability).map((r) => r.status)).toEqual([
			'corrupt',
			'outdated',
			'unknown',
			'ok',
		]);
	});

	it('breaks ties within a status by newest first', () => {
		const rows = [
			dump('ok', { filename: 'older.dump', created_at: '2026-01-01T00:00:00Z' }),
			dump('ok', { filename: 'newer.dump', created_at: '2026-07-01T00:00:00Z' }),
		];
		expect([...rows].sort(compareByRestorability).map((r) => r.filename)).toEqual([
			'newer.dump',
			'older.dump',
		]);
	});

	it('sorts a verdict this build does not know as the worst thing available', () => {
		// A server ahead of the frontend must not have its new verdict silently
		// treated as the healthiest.
		const rows = [dump('ok'), dump('surprise' as BackupStatus)];
		expect([...rows].sort(compareByRestorability)[0].status).toBe('surprise');
	});

	it('ranks every declared status', () => {
		expect(DUMP_STATUS_ORDER).toEqual(['corrupt', 'outdated', 'unknown', 'ok']);
	});
});
