import { writable } from 'svelte/store';

export type ToastVariant = 'info' | 'success' | 'error';

export interface ToastMessage {
	// Monotonic id so the host can tell a re-pushed identical message apart
	// from the one currently fading out (drives the re-trigger of the fly-in).
	id: number;
	message: string;
	variant: ToastVariant;
}

// The single app-wide transient toast. Components subscribe via ToastHost
// (mounted once in the root layout); callers fire toasts with pushToast().
// One slot, not a queue — a newer toast replaces the current one, which keeps
// the "fixed top-20" banner from ever stacking.
export const activeToast = writable<ToastMessage | null>(null);

let counter = 0;
let hideTimer: ReturnType<typeof setTimeout> | null = null;

/**
 * Show a toast for `durationMs`, then auto-clear. Each call cancels the
 * previous auto-hide so a rapid second toast gets its own full window
 * instead of inheriting the first one's remaining time.
 */
export function pushToast(
	message: string,
	variant: ToastVariant = 'info',
	durationMs = 3500,
): void {
	counter += 1;
	if (hideTimer !== null) clearTimeout(hideTimer);
	activeToast.set({ id: counter, message, variant });
	hideTimer = setTimeout(() => {
		activeToast.set(null);
		hideTimer = null;
	}, durationMs);
}
