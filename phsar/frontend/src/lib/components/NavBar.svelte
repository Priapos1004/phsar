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

    const menuItems: { href: string; label: string; adminOnly?: boolean }[] = [
        { href: '/settings', label: 'User Settings' },
        { href: '/library/add', label: 'Add to Library' },
        { href: '/admin', label: 'Admin', adminOnly: true },
        { href: '/statistics', label: 'Statistics' },
        { href: '/getting-started', label: 'Getting Started' },
    ];

    let visibleMenuItems = $derived(menuItems.filter((i) => !i.adminOnly || isAdmin));
</script>

<nav class="h-16 flex justify-between items-center px-8 py-4 bg-black/10 backdrop-blur">
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
                    <!-- The `child` snippet renders the menu item AS the <a>
                         so the whole padded area is the link target. Wrapping
                         <a href> inside a default <DropdownMenu.Item> made the
                         click target the menu-item div when users clicked the
                         padding; the menu closed but no navigation fired. -->
                    {#each visibleMenuItems as item (item.href)}
                        <DropdownMenu.Item>
                            {#snippet child({ props })}
                                <a href={item.href} {...props}>{item.label}</a>
                            {/snippet}
                        </DropdownMenu.Item>
                    {/each}
                    <DropdownMenu.Separator />
                    <DropdownMenu.Item variant="destructive" onclick={onLogout}>
                        Logout
                    </DropdownMenu.Item>
                </DropdownMenu.Content>
            </DropdownMenu.Root>
        </div>
    {/if}
</nav>
