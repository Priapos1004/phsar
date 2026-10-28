<script lang="ts">
    import { page } from '$app/state';
    import * as DropdownMenu from '$lib/components/ui/dropdown-menu';
    import JobBell from '$lib/components/JobBell.svelte';
    import * as cls from '$lib/styles/classes';
    import { isWithin } from '$lib/utils/filterLifecycle';

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
        { href: '/getting-started', label: 'Getting Started' },
    ];

    let visibleMenuItems = $derived(menuItems.filter((i) => !i.adminOnly || isAdmin));

    const sections = [
        { href: '/browse', label: 'Browse' },
        { href: '/ratings', label: 'Ratings' },
        { href: '/watchlist', label: 'Watchlist' },
    ];

    const isActive = (href: string) => isWithin(page.url.pathname, href);
</script>

<nav class="h-16 flex justify-between items-center gap-3 max-xs:gap-2 {cls.pageGutter} py-4 bg-black/10 backdrop-blur">
    <!-- On a phone the wordmark goes: with it, the sections, the bell and the
         avatar overflow a ~390px row. Below 360px the gutter (`cls.pageGutter`) and the gaps
         tighten, which is what fits the bell at 320. -->
    <div class="flex items-end gap-3 max-xs:gap-2 sm:gap-6">
        <a href="/" class="shrink-0 flex items-end hover:opacity-80 transition">
            <img src="/phsar_logo_transparent.png" alt="Phsar Logo" class="w-8 h-8" />
            <span class="hidden sm:inline ml-1 text-xl font-bold text-white">PHSAR</span>
        </a>
        {#each sections as section (section.href)}
            {@const active = isActive(section.href)}
            <a
                href={section.href}
                class="transition text-sm md:text-base {active ? 'text-primary' : 'text-white hover:text-primary/70'}"
                aria-current={active ? 'page' : undefined}
            >
                {section.label}
            </a>
        {/each}
    </div>

    {#if isAuthenticated}
        <div class="shrink-0 flex items-center gap-2">
            <!-- Bell + Add to Library are visible to restricted users too. The bell
                 will always be empty (they can't enqueue jobs) but they can browse
                 the recent-additions list on /library/add. -->
            <JobBell />
            <DropdownMenu.Root>
                <DropdownMenu.Trigger class="sm:ml-2 w-8 h-8 rounded-full bg-primary hover:bg-primary/80 flex items-center justify-center transition">
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
