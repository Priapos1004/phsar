<script lang="ts">
	import { onDestroy } from 'svelte';
	import { clearJobsFilter } from '$lib/stores/adminJobsFilter';
	import type { Snippet } from 'svelte';

	let { children }: { children: Snippet } = $props();

	// This layout cascades over every /admin route (including /admin/jobs/[uuid]),
	// so it stays mounted while moving within the admin section and unmounts only
	// when leaving it entirely. Clearing the Jobs Log filter here means re-entering
	// /admin from elsewhere (e.g. Settings) starts with a clean filter, while an
	// in-section hop (tab switch, job detail) keeps it.
	onDestroy(clearJobsFilter);
</script>

{@render children()}
