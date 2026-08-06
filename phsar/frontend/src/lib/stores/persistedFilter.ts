import { writable, type Writable } from 'svelte/store';
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

// Every filter created here registers its reset, so `resetAllPersistedFilters`
// can't miss one the way a hand-maintained key list (cf. bell-session.ts) can.
const resetters: (() => void)[] = [];

export function resetAllPersistedFilters(): void {
	for (const reset of resetters) reset();
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

	// Logout / user switch. The write-through subscriber persists the defaults,
	// which `read` treats identically to an absent key — so there is nothing
	// left to remove.
	resetters.push(() => store.set({ ...cfg.defaults }));
	return store;
}

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
