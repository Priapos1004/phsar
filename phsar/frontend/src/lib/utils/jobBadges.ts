import type { JobStatus } from '$lib/types/api';

// Single source of truth for status pill colors across the admin Jobs
// Log table (rows + children expander) and the detail page header.
// Adding a new status here propagates to every renderer.
export const STATUS_BADGE: Record<JobStatus, string> = {
	queued: 'bg-muted text-muted-foreground',
	running: 'bg-primary/15 text-primary',
	succeeded: 'bg-emerald-500/15 text-emerald-400',
	failed: 'bg-destructive/15 text-destructive',
};
