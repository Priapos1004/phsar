<script lang="ts">
	import SearchBar from '$lib/components/SearchBar.svelte';
	import { navigateToSearch } from '$lib/utils/navigation';
	import type { SearchParams } from '$lib/utils/search';
	import * as cls from '$lib/styles/classes';
    import ScrollableCard from '$lib/components/ScrollableCard.svelte';
    import InfoDiashow from '$lib/components/InfoDiashow.svelte';

	function handleSearch(data: SearchParams) {
		navigateToSearch(data);
	}
</script>

<div class={`${cls.container} pb-10 ${cls.sectionSpacing}`}>
	<!-- Top section: InfoDiashow -->
	<InfoDiashow />

	<!-- Search bar -->
	<SearchBar onSearch={handleSearch} />

	<!-- Sections below -->
	<div class={cls.sectionSpacing}>
        <ScrollableCard title="Recommended" text="Your recommended anime will appear here." />
        <ScrollableCard title="Lucky Find" text="Surprise anime picks coming soon!" />
        <ScrollableCard title="Upcoming" text="Upcoming anime will be listed here." />
    </div>
</div>
