<script lang="ts">
    import { onMount, getContext } from 'svelte';
    import { fly } from 'svelte/transition';
    import { api, ApiError } from '$lib/api';
    import { Button } from '$lib/components/ui/button';
    import * as Card from '$lib/components/ui/card';
    import * as Select from '$lib/components/ui/select';
    import { Label } from '$lib/components/ui/label';
    import { Separator } from '$lib/components/ui/separator';
    import { Download } from 'lucide-svelte';
    import { jwtDecode } from 'jwt-decode';
    import { token } from '$lib/stores/auth';
    import { userSettings } from '$lib/stores/userSettings';
    import { get } from 'svelte/store';
    import { API_URL } from '$lib/config';
    import DangerZone from '$lib/components/DangerZone.svelte';
    import type { UserSettings, UserSettingsUpdate } from '$lib/types/api';

    /**
     * Profile picture naming convention:
     *   filename: <color>__<name>__<version>.png  (e.g. sky_blue__frieren__v1.png)
     *   DB key:   <color> only (character/version-independent, enables future theme mapping)
     *   Frontend maps color → current filename for display
     */
    const PROFILE_PICTURES: { color: string; file: string; label: string }[] = [
        { color: 'rainbow', file: 'rainbow__coach__v2.png', label: 'Coach' },
        { color: 'white', file: 'white__asta__v4.png', label: 'Asta' },
        { color: 'brown', file: 'brown__attack_on_titan__v1.png', label: 'Attack on Titan' },
        { color: 'yellow', file: 'yellow__darkness__v1.png', label: 'Darkness' },
        { color: 'light_blue', file: 'light_blue__detective_conan__v1.png', label: 'Detective Conan' },
        { color: 'red', file: 'red__dr_stone__v1.png', label: 'Dr. Stone' },
        { color: 'sky_blue', file: 'sky_blue__frieren__v1.png', label: 'Frieren' },
        { color: 'orange', file: 'orange__naruto__v4.png', label: 'Naruto' },
        { color: 'pink', file: 'pink__nezuko__v10.png', label: 'Nezuko' },
        { color: 'purple', file: 'purple__shadow__v4.png', label: 'Shadow' },
        { color: 'blue', file: 'blue__solo_leveling__v2.png', label: 'Solo Leveling' },
        { color: 'black', file: 'black__tanya__v1.png', label: 'Tanya' },
        { color: 'green', file: 'green__tornado__v1.png', label: 'Tornado' },
    ];

    function profilePicUrl(colorKey: string): string {
        const pic = PROFILE_PICTURES.find(p => p.color === colorKey);
        return `/profile_pics/${pic ? pic.file : 'rainbow__coach__v2.png'}`;
    }

    const getUserRole = getContext<() => string | null>('userRole');

    // Read from the shared store so changes propagate immediately across the app
    let settings = $derived($userSettings);
    let showToast = $state(false);
    let error = $state('');

    onMount(async () => {
        // If store is empty (e.g. direct navigation), fetch from API
        if (!get(userSettings)) {
            try {
                userSettings.set(await api.get<UserSettings>('/users/settings'));
            } catch (err) {
                if (err instanceof ApiError) error = err.detail;
                else error = 'Failed to load settings.';
            }
        }
    });

    async function saveSetting(update: UserSettingsUpdate) {
        if (!settings) return;
        try {
            const updated = await api.put<UserSettings>('/users/settings', update);
            userSettings.set(updated);
            showToast = true;
            setTimeout(() => showToast = false, 2000);
        } catch (err) {
            if (err instanceof ApiError) error = err.detail;
            else error = 'Failed to save settings.';
        }
    }

    async function downloadExport(format: 'json' | 'csv') {
        const currentToken = get(token);
        const resp = await fetch(`${API_URL}/users/export?format=${format}`, {
            headers: { Authorization: `Bearer ${currentToken}` },
        });
        if (!resp.ok) {
            error = 'Export failed.';
            return;
        }
        const blob = await resp.blob();
        const url = URL.createObjectURL(blob);
        const a = document.createElement('a');
        a.href = url;
        let username = 'user';
        try {
            const decoded = jwtDecode<{ sub?: string }>(currentToken!);
            if (decoded.sub) username = decoded.sub;
        } catch { /* use fallback */ }
        const d = new Date();
        const today = `${d.getFullYear()}_${String(d.getMonth() + 1).padStart(2, '0')}_${String(d.getDate()).padStart(2, '0')}`;
        a.download = `phsar_export_${username}_${today}.${format}`;
        a.click();
        URL.revokeObjectURL(url);
    }

    let role = $derived(getUserRole());
    let isRestricted = $derived(role === 'restricted_user');

    // If the stored profile_picture doesn't match any known color, treat it as the default
    function isSelectedPic(storedKey: string, picColor: string): boolean {
        const knownColors = PROFILE_PICTURES.map(p => p.color);
        if (knownColors.includes(storedKey)) return storedKey === picColor;
        return picColor === 'rainbow'; // fallback highlights the default
    }
</script>

<div class="mx-auto max-w-2xl space-y-6">
    <h1 class="text-2xl font-bold text-white">Settings</h1>

    {#if error}
        <p class="text-destructive text-sm">{error}</p>
    {/if}

    {#if settings}
        <!-- Profile Picture -->
        <Card.Root>
            <Card.Header>
                <h2 class="text-lg font-semibold text-card-foreground">Profile Picture</h2>
            </Card.Header>
            <Card.Content>
                <div class="grid grid-cols-5 sm:grid-cols-7 gap-3">
                    {#each PROFILE_PICTURES as pic}
                        <button
                            class="rounded-lg overflow-hidden border-2 transition {isSelectedPic(settings.profile_picture, pic.color) ? 'border-primary ring-2 ring-primary/50' : 'border-transparent hover:border-muted-foreground/30'}"
                            onclick={() => saveSetting({ profile_picture: pic.color })}
                            title={pic.label}
                        >
                            <img
                                src={profilePicUrl(pic.color)}
                                alt={pic.label}
                                class="w-full aspect-square object-cover"
                            />
                        </button>
                    {/each}
                </div>
            </Card.Content>
        </Card.Root>

        <!-- Preferences -->
        <Card.Root>
            <Card.Header>
                <h2 class="text-lg font-semibold text-card-foreground">Preferences</h2>
            </Card.Header>
            <Card.Content class="space-y-5">
                <!-- Name Language -->
                <div class="flex items-center justify-between">
                    <Label>Name Language</Label>
                    <Select.Root
                        type="single"
                        value={settings.name_language}
                        onValueChange={(v) => { if (v) saveSetting({ name_language: v as UserSettings['name_language'] }); }}
                    >
                        <Select.Trigger class="w-40">
                            {settings.name_language.charAt(0).toUpperCase() + settings.name_language.slice(1)}
                        </Select.Trigger>
                        <Select.Content>
                            <Select.Item value="english">English</Select.Item>
                            <Select.Item value="japanese">Japanese</Select.Item>
                            <Select.Item value="romaji">Romaji</Select.Item>
                        </Select.Content>
                    </Select.Root>
                </div>

                <Separator />

                <!-- Default Search View -->
                <div class="flex items-center justify-between">
                    <Label>Default Search View</Label>
                    <Select.Root
                        type="single"
                        value={settings.default_search_view}
                        onValueChange={(v) => { if (v) saveSetting({ default_search_view: v as UserSettings['default_search_view'] }); }}
                    >
                        <Select.Trigger class="w-40">
                            {settings.default_search_view.charAt(0).toUpperCase() + settings.default_search_view.slice(1)}
                        </Select.Trigger>
                        <Select.Content>
                            <Select.Item value="anime">Anime</Select.Item>
                            <Select.Item value="media">Media</Select.Item>
                        </Select.Content>
                    </Select.Root>
                </div>

                {#if !isRestricted}
                    <Separator />

                    <!-- Rating Step -->
                    <div class="flex items-center justify-between">
                        <Label>Rating Step</Label>
                        <Select.Root
                            type="single"
                            value={settings.rating_step}
                            onValueChange={(v) => { if (v) saveSetting({ rating_step: v as UserSettings['rating_step'] }); }}
                        >
                            <Select.Trigger class="w-40">
                                {settings.rating_step}
                            </Select.Trigger>
                            <Select.Content>
                                <Select.Item value="0.5">0.5</Select.Item>
                                <Select.Item value="0.25">0.25</Select.Item>
                                <Select.Item value="0.1">0.1</Select.Item>
                                <Select.Item value="0.01">0.01</Select.Item>
                            </Select.Content>
                        </Select.Root>
                    </div>
                {/if}

                <Separator />

                <!-- Spoiler Level -->
                <div class="flex items-center justify-between">
                    <div>
                        <Label>Spoiler Protection</Label>
                        <p class="text-xs text-muted-foreground mt-0.5">
                            {#if settings.spoiler_level === 'off'}
                                No spoiler protection
                            {:else if settings.spoiler_level === 'blur'}
                                Blur covers and descriptions for unrated media
                            {:else}
                                Hide unrated media from search results
                            {/if}
                        </p>
                    </div>
                    <Select.Root
                        type="single"
                        value={settings.spoiler_level}
                        onValueChange={(v) => { if (v) saveSetting({ spoiler_level: v as UserSettings['spoiler_level'] }); }}
                    >
                        <Select.Trigger class="w-40">
                            {settings.spoiler_level === 'off' ? 'Off' : settings.spoiler_level === 'blur' ? 'Blur' : 'Hide'}
                        </Select.Trigger>
                        <Select.Content>
                            <Select.Item value="off">Off</Select.Item>
                            <Select.Item value="blur">Blur</Select.Item>
                            <Select.Item value="hide">Hide</Select.Item>
                        </Select.Content>
                    </Select.Root>
                </div>
            </Card.Content>
        </Card.Root>

        <!-- Data Export -->
        {#if !isRestricted}
            <Card.Root>
                <Card.Header>
                    <h2 class="text-lg font-semibold text-card-foreground">Data Export</h2>
                    <p class="text-sm text-muted-foreground">Download your ratings and watchlist</p>
                </Card.Header>
                <Card.Content>
                    <div class="flex gap-3">
                        <Button variant="secondary" onclick={() => downloadExport('json')}>
                            <Download class="w-4 h-4 mr-2" />
                            JSON
                        </Button>
                        <Button variant="secondary" onclick={() => downloadExport('csv')}>
                            <Download class="w-4 h-4 mr-2" />
                            CSV
                        </Button>
                    </div>
                </Card.Content>
            </Card.Root>
        {/if}

        <!-- Danger Zone -->
        <DangerZone {isRestricted} />

    {:else if !error}
        <p class="text-muted-foreground">Loading settings...</p>
    {/if}
</div>

{#if showToast}
    <div
        class="fixed top-20 left-1/2 -translate-x-1/2 z-50 bg-primary text-primary-foreground px-4 py-2 rounded-lg shadow-lg text-sm font-medium"
        in:fly={{ y: -20, duration: 200 }}
        out:fly={{ y: -20, duration: 150 }}
    >
        Settings updated
    </div>
{/if}
