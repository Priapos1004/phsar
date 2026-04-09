<script lang="ts">
	import SearchBar from '$lib/components/SearchBar.svelte';
	import { navigateToSearch } from '$lib/utils/navigation';
	import { userSettings } from '$lib/stores/userSettings';
	import type { MediaSearchFilters } from '$lib/utils/search';
	import * as cls from '$lib/styles/classes';
    import ScrollableCard from '$lib/components/ScrollableCard.svelte';
    import InfoDiashow from '$lib/components/InfoDiashow.svelte';

	let defaultView = $derived($userSettings?.default_search_view ?? 'anime');

	function handleSearch(data: MediaSearchFilters) {
		navigateToSearch({ ...data, view_type: defaultView });
	}
</script>

<div class={`${cls.container} pb-10 ${cls.sectionSpacing}`}>
	<!-- Top section: InfoDiashow -->
	<InfoDiashow />

	<!-- Search bar -->
	<SearchBar viewType={defaultView} onSearch={handleSearch} />

	<!-- Sections below -->
	<div class={cls.sectionSpacing}>
        <ScrollableCard title="Recommended" text="Your recommended animes will appear here." />
        <ScrollableCard title="Lucky Find" text="Surprise anime picks coming soon!" />
        <ScrollableCard title="Upcoming" text="Upcoming animes will be listed here." />
    </div>
</div>
