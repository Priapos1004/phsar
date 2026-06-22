/** Tab keys for the admin page. Extending this requires:
 *  - adding the new entry to TABS in routes/admin/+page.svelte
 *  - rendering the corresponding content branch in that file
 */
export type AdminTabKey = 'overview' | 'jobs' | 'tokens' | 'curation' | 'completion' | 'backups';
