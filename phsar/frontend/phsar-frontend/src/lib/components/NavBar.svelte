<script lang="ts">
    export let isAuthenticated: boolean;
    export let onLogout: () => void;

    let dropdownOpen = false;

    function toggleDropdown() {
        dropdownOpen = !dropdownOpen;
    }
</script>

<nav class="flex justify-between items-center px-8 py-4">
    <!-- LEFT: Logo + main links aligned at bottom -->
    <div class="flex items-end gap-6">
        <a href="/" class="flex items-end hover:opacity-80 transition">
            <img src="/phsar_logo_transparent.png" alt="Phsar Logo" class="w-8 h-8" />
            <span class="ml-1 text-xl font-bold text-white">PHSAR</span>
        </a>
        <a href="/ratings" class="text-white hover:text-purple-400 transition text-sm md:text-base">
            Ratings
        </a>
        <a href="/watchlist" class="text-white hover:text-purple-400 transition text-sm md:text-base">
            Watchlist
        </a>
    </div>

    <!-- RIGHT: User dropdown -->
    {#if isAuthenticated}
        <div class="relative">
            <button
                on:click={toggleDropdown}
                class="ml-4 w-8 h-8 rounded-full bg-purple-700 hover:bg-purple-600 flex items-center justify-center transition"
            >
                <span class="text-white text-sm font-semibold">U</span>
            </button>

            {#if dropdownOpen}
                <div class="absolute right-0 mt-2 w-48 bg-white rounded-md shadow-lg py-2 z-50">
                    <a href="/settings" class="block px-4 py-2 text-gray-700 hover:bg-gray-100">User Settings</a>
                    <a href="/statistics" class="block px-4 py-2 text-gray-700 hover:bg-gray-100">Statistics</a>
                    <a href="/getting-started" class="block px-4 py-2 text-gray-700 hover:bg-gray-100">Getting Started</a>
                    <button
                        on:click={onLogout}
                        class="w-full text-left px-4 py-2 text-red-600 hover:bg-gray-100"
                    >
                        Logout
                    </button>
                </div>
            {/if}
        </div>
    {/if}
</nav>
