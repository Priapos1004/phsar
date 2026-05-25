<script lang="ts">
	import { onMount, getContext } from 'svelte';
	import { goto } from '$app/navigation';
	import { page } from '$app/state';
	import BackupsCard from '$lib/components/BackupsCard.svelte';
	import MergeCandidatesCard from '$lib/components/MergeCandidatesCard.svelte';
	import SplitCandidatesCard from '$lib/components/SplitCandidatesCard.svelte';
	import AdminOverviewTab from '$lib/components/admin/AdminOverviewTab.svelte';
	import RegistrationTokensCard from '$lib/components/admin/RegistrationTokensCard.svelte';
	import AdminTabNav from '$lib/components/admin/AdminTabNav.svelte';
	import type { AdminTabKey } from '$lib/components/admin/types';

	const getUserRole = getContext<() => string | null>('userRole');
	const getUsername = getContext<() => string | null>('username');

	const TABS: { key: AdminTabKey; label: string }[] = [
		{ key: 'overview', label: 'Overview' },
		{ key: 'tokens', label: 'Tokens' },
		{ key: 'curation', label: 'Curation' },
		{ key: 'backups', label: 'Backups' },
	];
	const DEFAULT_TAB: AdminTabKey = 'overview';
	const TAB_KEYS = new Set(TABS.map((t) => t.key));

	// Fall back to DEFAULT_TAB on unknown values so a stale bookmark or a
	// retired tab key never lands the admin on a blank page.
	let active = $derived.by(() => {
		const raw = page.url.searchParams.get('tab');
		return raw && TAB_KEYS.has(raw as AdminTabKey) ? (raw as AdminTabKey) : DEFAULT_TAB;
	});

	onMount(() => {
		if (getUserRole() !== 'admin') goto('/');
	});
</script>

<svelte:head>
	<title>Admin — Phsar</title>
</svelte:head>

<div class="mx-auto max-w-3xl space-y-6">
	<h1 class="text-2xl font-bold text-white">Admin</h1>

	<AdminTabNav tabs={TABS} defaultTab={DEFAULT_TAB} />

	<!-- Tabs eager-render and stay mounted; visibility toggles via class:hidden.
		 Admin sessions usually touch several tabs in a row (tokens → curation →
		 backups), so the one-time parallel-fetch cost on first paint buys
		 instant tab switches for the rest of the session. No card polls, so
		 keeping them mounted doesn't generate ongoing traffic. -->
	<div class:hidden={active !== 'overview'}>
		<AdminOverviewTab />
	</div>
	<div class:hidden={active !== 'tokens'}>
		<RegistrationTokensCard />
	</div>
	<div class:hidden={active !== 'curation'} class="space-y-6">
		<MergeCandidatesCard />
		<SplitCandidatesCard />
	</div>
	<div class:hidden={active !== 'backups'}>
		<BackupsCard currentUsername={getUsername() ?? ''} />
	</div>
</div>
