/**
 * The per-tab stash that lets a re-login pick up where a lapsed session left off.
 *
 * Only the list filters live here; the route travels as `?next=` in
 * `utils/returnTo`. Why the two are split: `docs/features/navigation.md`.
 *
 * A separate key rather than a change to when the live `phsar.filter.*` keys
 * are cleared. `clearPerUserStores` wipes those on `token.set(null)`, so the
 * owner check below is the *only* way the outgoing user's filters can come
 * back, not a second line of defence behind something laxer.
 *
 * The snapshot registry fills at module evaluation (`stores/persistedFilter`),
 * and this module deliberately does NOT import `utils/filterLifecycle` to force
 * that: `filterLifecycle` reaches `utils/navigation` -> `api`, and `api` is
 * itself a caller here, so the import would close a cycle whose evaluation
 * order decides whether `filterLifecycle` reads `DETAIL_TYPES` before it is
 * initialised. The root layout — component and load — imports `filterLifecycle`
 * instead, which populates the registry before any caller here can run.
 */
import { get } from 'svelte/store';
import { browser } from '$app/environment';
import { token } from '$lib/stores/auth';
import {
	restoreAllPersistedFilters,
	snapshotAllPersistedFilters,
} from '$lib/stores/persistedFilter';
import { loginUrlReturningTo } from '$lib/utils/returnTo';
import { subFromToken } from '$lib/utils/sessionTimeout';

const RESUME_KEY = 'phsar.resume';

/** Bump whenever the envelope's shape changes. */
const RESUME_VERSION = 1;

/**
 * How long a stash stays usable. Long enough to cover stepping away from a
 * session that then lapsed, short enough that filters chosen before lunch don't
 * silently reappear after it. sessionStorage already bounds this to one tab —
 * the TTL is what bounds a tab left open inside it.
 */
const RESUME_TTL_MS = 3 * 60 * 60 * 1000;

/**
 * What `consumeResume` found.
 *
 * `foreign` is the one a caller must act on beyond the filters — see
 * `landAfterAuth`. `stale` is the same user past the TTL: only the filters are
 * too old to reuse.
 */
export type ResumeVerdict = 'restored' | 'stale' | 'foreign' | 'none';

interface ResumeEnvelope {
	v: number;
	owner: string;
	at: number;
	filters: Record<string, unknown>;
}

/**
 * Record the filters for whoever is being signed out.
 *
 * Must be called BEFORE `token.set(null)` at every site: that subscriber clears
 * the very stores this reads. Without an owner there is nothing to bind the
 * stash to, so it writes nothing and the route restores on its own.
 */
export function stashResume(owner: string | null): void {
	if (!browser || !owner) return;
	try {
		const envelope: ResumeEnvelope = {
			v: RESUME_VERSION,
			owner,
			at: Date.now(),
			filters: snapshotAllPersistedFilters(),
		};
		sessionStorage.setItem(RESUME_KEY, JSON.stringify(envelope));
	} catch {
		// Private mode / quota. Losing the stash costs the filters, not the route.
	}
}

export function clearResume(): void {
	if (!browser) return;
	try {
		sessionStorage.removeItem(RESUME_KEY);
	} catch {
		// Storage disabled entirely; there was nothing to remove.
	}
}

/**
 * Read, discard, and where it applies re-apply the stash for the user who just
 * signed in.
 *
 * One-shot: the key is removed whatever the verdict, so no stash can survive
 * into a second login.
 *
 * A null owner — a token whose `sub` would not decode — is treated as `foreign`
 * rather than waved through. "Cannot prove this is the same user" has to land on
 * the same side as "this is a different user", or the one case nobody tests
 * becomes the one that leaks a filter set.
 */
export function consumeResume(owner: string | null): ResumeVerdict {
	if (!browser) return 'none';
	if (!owner) {
		clearResume();
		return 'foreign';
	}

	let raw: string | null;
	try {
		raw = sessionStorage.getItem(RESUME_KEY);
	} catch {
		return 'none';
	}
	// After the read but before any verdict, so no stash reaches a second login.
	// After the empty check too — the common login has nothing to remove.
	if (!raw) return 'none';
	clearResume();

	let parsed: Partial<ResumeEnvelope> | null;
	try {
		parsed = JSON.parse(raw);
	} catch {
		return 'none';
	}

	// A version bump means the envelope moved. Discard rather than half-apply —
	// the same rule, for the same reason, as persistedFilter's own envelope.
	if (!parsed || parsed.v !== RESUME_VERSION || typeof parsed.owner !== 'string') return 'none';
	if (parsed.owner !== owner) return 'foreign';
	if (typeof parsed.at !== 'number' || Date.now() - parsed.at >= RESUME_TTL_MS) return 'stale';
	if (!parsed.filters || typeof parsed.filters !== 'object') return 'stale';

	restoreAllPersistedFilters(parsed.filters as Record<string, unknown>);
	return 'restored';
}

/**
 * Everything an involuntary exit owes the user, and the /login URL to leave for.
 *
 * The ordering is the reason this is a function rather than three lines at each
 * of the sites that need it: the stash must be taken while the token still says
 * whose filters these are, and `token.set(null)`'s subscriber clears those very
 * stores synchronously. Every caller therefore has to run this BEFORE clearing
 * the token — one call to get wrong rather than three.
 *
 * Safe on the no-token path: `subFromToken(null)` is null and `stashResume`
 * writes nothing, leaving just the route to carry.
 */
export function captureReturnTarget(url: URL): string {
	stashResume(subFromToken(get(token)));
	return loginUrlReturningTo(url);
}

/**
 * Where a successful sign-in or registration should land, consuming the stash
 * on the way.
 *
 * Owns the one coupling between the two mechanisms: a stash belonging to
 * somebody else means the `next` captured beside it was theirs too, so a
 * different person signing in at this browser starts at the beginning rather
 * than on the last person's page. Here rather than in the auth pages because it
 * is a policy, and a third entry point must not be able to omit it by writing a
 * plainer `goto`.
 */
export function landAfterAuth(accessToken: string, next: string | null): string {
	return consumeResume(subFromToken(accessToken)) === 'foreign' ? '/' : (next ?? '/');
}
