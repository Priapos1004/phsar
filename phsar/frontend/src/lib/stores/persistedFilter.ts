import { get, writable, type Writable } from 'svelte/store';
import { browser } from '$app/environment';

/**
 * sessionStorage-backed list-control state (the /ratings, /watchlist and
 * /admin?tab=jobs filters).
 *
 * Per-tab, not per-browser: two tabs keep independent filters, and a filter set
 * today can't greet the user next week.
 *
 * Storage is a mirror of the store, not a second source of truth — a subscriber
 * writes every change through, so each store's own `clearXFilter()` persists
 * its reset with no extra call.
 *
 * Adding one: export a `clearXFilter()` deciding which display prefs survive, then
 * register it in `utils/filterLifecycle`'s `SECTION_FILTERS` — and widen the `ALL`
 * list in `src/tests/filter-lifecycle.test.ts`, which pins the set.
 *
 * That registration also guards logout: `registered` fills at *module evaluation*,
 * so a filter clears only if its module has loaded. `filterLifecycle` imports every
 * `clearXFilter` and the root layout imports `filterLifecycle` — a filter missing
 * from `SECTION_FILTERS` loads only on its own page, so a value set there outlives
 * the logout that should have cleared it. The same caveat governs the snapshot
 * below: an unloaded filter is absent from it, and comes back at its defaults.
 */

interface PersistedFilterConfig<T extends object> {
	/** sessionStorage key. Namespaced `phsar.filter.*`, like `phsar.bell*`. */
	key: string;
	/** Bump whenever a field is added, renamed or retyped. */
	version: number;
	defaults: T;
	/**
	 * Whitelist a raw parsed object into a valid state. Mandatory because the
	 * hazard is bad VALUES, not a bad shape: unions must be checked against
	 * their key sets. Use `pickKey` / `pickStrings` / `pickNumbers` below.
	 */
	sanitize: (raw: Record<string, unknown>) => T;
}

interface RegisteredFilter {
	key: string;
	snapshot: () => object;
	restore: (raw: unknown) => void;
	reset: () => void;
}

// Every filter created here registers itself, so no whole-set operation can
// miss one the way a hand-maintained key list (cf. bell-session.ts) can.
const registered: RegisteredFilter[] = [];

export function resetAllPersistedFilters(): void {
	for (const entry of registered) entry.reset();
}

/**
 * Every filter's current state, keyed by storage key.
 *
 * For `utils/resumeSession`, which stashes this before a lapsed session clears
 * the live keys. Returns live store values — the caller serializes immediately.
 */
export function snapshotAllPersistedFilters(): Record<string, object> {
	const out: Record<string, object> = {};
	for (const entry of registered) out[entry.key] = entry.snapshot();
	return out;
}

/**
 * Apply a snapshot back onto the stores.
 *
 * Routed through each filter's own `sanitize`, because a snapshot read back out
 * of sessionStorage is exactly as untrusted as the live keys `read` guards —
 * same hazard, same whitelist. Per-entry isolation so one unusable entry costs
 * only its own section; a missing key leaves that store untouched.
 */
export function restoreAllPersistedFilters(snapshot: Record<string, unknown>): void {
	for (const entry of registered) {
		const raw = snapshot[entry.key];
		if (!raw || typeof raw !== 'object') continue;
		try {
			entry.restore(raw);
		} catch {
			// A sanitize that threw. Leave this store at whatever it holds.
		}
	}
}

function serialize(version: number, state: object): string {
	return JSON.stringify({ v: version, state });
}

function read<T extends object>(cfg: PersistedFilterConfig<T>): T {
	try {
		const raw = browser && sessionStorage.getItem(cfg.key);
		const parsed: { v?: unknown; state?: unknown } | null = raw ? JSON.parse(raw) : null;
		// A version bump means fields moved. Discard rather than half-apply: a
		// stale value that still type-checks is worse than a clean reset.
		if (parsed?.v === cfg.version && typeof parsed.state === 'object' && parsed.state) {
			return cfg.sanitize(parsed.state as Record<string, unknown>);
		}
	} catch {
		// Corrupt JSON, a sanitize that threw, or storage disabled entirely.
	}
	return { ...cfg.defaults };
}

export function createPersistedFilter<T extends object>(
	cfg: PersistedFilterConfig<T>
): Writable<T> {
	const initial = read(cfg);
	const store = writable<T>(initial);

	if (browser) {
		// Seeded from the initial value, so the subscriber's immediate first
		// fire doesn't write back what `read` just returned — otherwise every
		// page load, including an anonymous visitor on /login, creates three
		// keys full of pure defaults. It also absorbs the no-op clears: a
		// navigation resets up to three sections, and the common case is that
		// none of them was ever filtered.
		let lastWritten = serialize(cfg.version, initial);
		store.subscribe((value) => {
			const next = serialize(cfg.version, value);
			if (next === lastWritten) return;
			lastWritten = next;
			try {
				sessionStorage.setItem(cfg.key, next);
			} catch {
				// Private mode / quota. The in-memory store still works; only
				// surviving a refresh is lost, which is the enhancement here.
			}
		});
	}

	// Reset is logout / user switch: the write-through subscriber persists the
	// defaults, which `read` treats identically to an absent key — so there is
	// nothing left to remove. Snapshot and restore serve the resume stash, and
	// ride the same subscriber, so a restore is persisted like any other change.
	registered.push({
		key: cfg.key,
		snapshot: () => get(store),
		restore: (raw) => store.set(cfg.sanitize(raw as Record<string, unknown>)),
		reset: () => store.set({ ...cfg.defaults }),
	});
	return store;
}

/** `asc | desc` — every sortable list section has a direction. */
export type Direction = 'asc' | 'desc';

/** Whitelists shared by the ratings + watchlist filters, whose view and grain
 *  unions are the same two pairs. Kept beside `pickKey` (which consumes them)
 *  rather than duplicated per store. */
export const VIEW_KEYS: Record<'grid' | 'table', true> = { grid: true, table: true };
export const GRAIN_KEYS: Record<'anime' | 'media', true> = { anime: true, media: true };
export const DIRECTION_KEYS: Record<Direction, true> = { asc: true, desc: true };

/**
 * Whitelist a stored string against a `Record<Union, …>` key set.
 *
 * Takes a Record rather than an array so TypeScript enforces exhaustiveness at
 * the definition — a union member the caller forgets is a compile error, not a
 * value that silently falls back forever. Same shape as `JOB_KIND_LABELS` /
 * `STATUS_BADGE`, which `adminJobsFilter` already whitelists against.
 */
export function pickKey<T extends string>(
	raw: unknown,
	allowed: Record<T, unknown>,
	fallback: T
): T {
	return typeof raw === 'string' && Object.hasOwn(allowed, raw) ? (raw as T) : fallback;
}

export function pickStrings(raw: unknown): string[] {
	return Array.isArray(raw) ? raw.filter((v): v is string => typeof v === 'string') : [];
}

export function pickNumbers(raw: unknown): number[] {
	return Array.isArray(raw)
		? raw.filter((v): v is number => typeof v === 'number' && Number.isFinite(v))
		: [];
}
