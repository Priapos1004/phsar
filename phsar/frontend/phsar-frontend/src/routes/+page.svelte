<script lang="ts">
    import { getCurrentSeason } from '$lib/utils/getSeason';
    import SearchBar from '$lib/components/SearchBar.svelte';

    const currentSeason = getCurrentSeason();
</script>

<div class="max-w-5xl mx-auto px-4 pb-10 space-y-8">
    <!-- Top section: Season box -->
    <div class="bg-purple-700 text-white rounded-2xl p-6 shadow-lg flex flex-col items-center">
        <h2 class="text-3xl font-bold mb-2">Current Season</h2>
        <p class="text-3xl">{currentSeason}</p>
        <!-- (Optional later) slideshow or image goes here -->
    </div>

    <!-- Search bar -->
    <SearchBar onSearch={(data) => console.log('Received search:', data)} />

    <!-- Sections below -->
    <div class="space-y-8">
        <section>
            <h3 class="text-2xl font-semibold mb-4 text-white">Recommended</h3>
            <div class="bg-white/80 backdrop-blur rounded-xl p-4 shadow">
                <p class="text-gray-700">Your recommended anime will appear here.</p>
            </div>
        </section>
    
        <section>
            <h3 class="text-2xl font-semibold mb-4 text-white">Lucky Find</h3>
            <div class="bg-white/80 backdrop-blur rounded-xl p-4 shadow">
                <p class="text-gray-700">Surprise anime picks coming soon!</p>
            </div>
        </section>
    
        <section>
            <h3 class="text-2xl font-semibold mb-4 text-white">Upcoming</h3>
            <div class="bg-white/80 backdrop-blur rounded-xl p-4 shadow">
                <p class="text-gray-700">Upcoming anime will be listed here.</p>
            </div>
        </section>
    </div>
</div>
