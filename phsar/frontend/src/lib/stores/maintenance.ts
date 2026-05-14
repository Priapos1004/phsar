import { createBumpStore } from './_bumpStore';

/**
 * api.ts bumps this whenever it gets a 503-with-{maintenance:true} so the
 * MaintenanceBanner refetches /maintenance/status immediately instead of
 * waiting for its 60s poll. Without this, a login submit during a window
 * the banner hasn't observed yet would briefly show no banner — the
 * user-facing "after relogin the banner is still there" / "no banner
 * during a known maintenance" gap.
 */
export const [maintenanceRefresh, bumpMaintenanceRefresh] = createBumpStore();
