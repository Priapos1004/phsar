<script lang="ts">
    import * as DropdownMenu from '$lib/components/ui/dropdown-menu';
    import JobBell from '$lib/components/JobBell.svelte';

    interface Props {
        isAuthenticated: boolean;
        username: string | null;
        isAdmin: boolean;
        onLogout: () => void;
    }

    let { isAuthenticated, username = null, isAdmin = false, onLogout }: Props = $props();
</script>

<nav class="sticky top-0 z-50 h-16 flex justify-between items-center px-8 py-4 bg-black/10 backdrop-blur">
    <div class="flex items-end gap-6">
        <a href="/" class="flex items-end hover:opacity-80 transition">
            <img src="/phsar_logo_transparent.png" alt="Phsar Logo" class="w-8 h-8" />
            <span class="ml-1 text-xl font-bold text-white">PHSAR</span>
        </a>
        <a href="/ratings" class="text-white hover:text-primary/70 transition text-sm md:text-base">
            Ratings
        </a>
        <a href="/watchlist" class="text-white hover:text-primary/70 transition text-sm md:text-base">
            Watchlist
        </a>
    </div>

    {#if isAuthenticated}
        <div class="flex items-center gap-2">
            <!-- Bell + Add to Library are visible to restricted users too. The bell
                 will always be empty (they can't enqueue jobs) but they can browse
                 the recent-additions list on /library/add. -->
            <JobBell />
            <DropdownMenu.Root>
                <DropdownMenu.Trigger class="ml-2 w-8 h-8 rounded-full bg-primary hover:bg-primary/80 flex items-center justify-center transition">
                    <span class="text-white text-sm font-semibold">{username ? username[0].toUpperCase() : 'U'}</span>
                </DropdownMenu.Trigger>
                <DropdownMenu.Content class="w-48" align="end">
                    <DropdownMenu.Item>
                        <a href="/settings" class="w-full">User Settings</a>
                    </DropdownMenu.Item>
                    <DropdownMenu.Item>
                        <a href="/library/add" class="w-full">Add to Library</a>
                    </DropdownMenu.Item>
                    {#if isAdmin}
                        <DropdownMenu.Item>
                            <a href="/admin" class="w-full">Admin</a>
                        </DropdownMenu.Item>
                    {/if}
                    <DropdownMenu.Item>
                        <a href="/statistics" class="w-full">Statistics</a>
                    </DropdownMenu.Item>
                    <DropdownMenu.Item>
                        <a href="/getting-started" class="w-full">Getting Started</a>
                    </DropdownMenu.Item>
                    <DropdownMenu.Separator />
                    <DropdownMenu.Item variant="destructive" onclick={onLogout}>
                        Logout
                    </DropdownMenu.Item>
                </DropdownMenu.Content>
            </DropdownMenu.Root>
        </div>
    {/if}
</nav>
