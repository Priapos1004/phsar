<script lang="ts">
    import { page } from '$app/state';
    import { token } from '$lib/stores/auth';
    import { userSettings } from '$lib/stores/userSettings';
    import { spoilerVisibility, refreshSpoilerVisibility } from '$lib/stores/spoilerVisibility';
    import { onMount, setContext } from 'svelte';
    import { jwtDecode } from 'jwt-decode';
    import { api } from '$lib/api';
    import NavBar from '$lib/components/NavBar.svelte';
    import TokenExpiryDialog from '$lib/components/TokenExpiryDialog.svelte';
    import LoadingScreen from '$lib/components/LoadingScreen.svelte';
    import VersionFooter from '$lib/components/VersionFooter.svelte';
    import { getThemeCssClass, isValidTheme } from '$lib/themes';
    import '../app.css';
    import type { Snippet } from 'svelte';
    import type { UserSettings } from '$lib/types/api';

    let { children }: { children: Snippet } = $props();

    let loading = $state(true);
    let isAuthenticated = $state(false);
    let userRole = $state<string | null>(null);
    let username = $state<string | null>(null);
    let showExpiryDialog = $state(false);
    let expiryTimer: ReturnType<typeof setTimeout> | null = null;

    setContext('userRole', () => userRole);
    setContext('username', () => username);

    interface DecodedToken {
      sub: string;
      role: string;
      exp: number;
    }

    function clearExpiryTimer() {
      if (expiryTimer) {
        clearTimeout(expiryTimer);
        expiryTimer = null;
      }
    }

    onMount(() => {
      const unsubscribe = token.subscribe(async (val) => {
        clearExpiryTimer();
        showExpiryDialog = false;
        isAuthenticated = !!val;
        if (val) {
          try {
            const decoded = jwtDecode<DecodedToken>(val);
            userRole = decoded.role;
            username = decoded.sub;

            // Set expiry timer based on JWT exp claim
            const msUntilExpiry = decoded.exp * 1000 - Date.now();
            if (msUntilExpiry <= 0) {
              showExpiryDialog = true;
            } else {
              expiryTimer = setTimeout(() => { showExpiryDialog = true; }, msUntilExpiry);
            }

            // Fetch settings and spoiler visibility in parallel to avoid serial latency
            try {
              const [settings] = await Promise.all([
                api.get<UserSettings>('/users/settings'),
                refreshSpoilerVisibility(),
              ]);
              userSettings.set(settings);
              // Clear visibility store if spoiler protection is off
              if (settings.spoiler_level === 'off') {
                spoilerVisibility.set(null);
              }
            } catch {
              userSettings.set(null);
              spoilerVisibility.set(null);
            }
          } catch {
            token.set(null);
            userRole = null;
            username = null;
            userSettings.set(null);
            spoilerVisibility.set(null);
          }
        } else {
          userRole = null;
          username = null;
          userSettings.set(null);
          spoilerVisibility.set(null);
        }
        loading = false;
      });

      return () => {
        unsubscribe();
        clearExpiryTimer();
      };
    });

    // Apply theme CSS class to <html> and sync to localStorage for FOUC prevention.
    // Must be on <html> (not <body>) so overrides sit at the same :root level
    // where @theme inline defines the CSS custom properties.
    $effect(() => {
      const themeKey = $userSettings?.theme;
      const el = document.documentElement;
      const toRemove = [...el.classList].filter(cls => cls.startsWith('theme-'));
      toRemove.forEach(cls => el.classList.remove(cls));
      if (themeKey && isValidTheme(themeKey)) {
        const cssClass = getThemeCssClass(themeKey);
        if (cssClass) {
          el.classList.add(cssClass);
          localStorage.setItem('phsar-theme', themeKey);
        } else {
          localStorage.removeItem('phsar-theme');
        }
      } else {
        localStorage.removeItem('phsar-theme');
      }
    });

    function handleLogout() {
      token.set(null);
      window.location.href = '/login';
    }
</script>

{#if loading}
    <LoadingScreen />
{:else}
    {#if page.url.pathname !== '/login' && page.url.pathname !== '/register'}
      <NavBar {isAuthenticated} {username} isAdmin={userRole === 'admin'} onLogout={handleLogout} />
    {/if}

    <main class="min-h-screen px-8 pt-4 pb-8">
      {@render children()}
    </main>

    <VersionFooter />

    <TokenExpiryDialog open={showExpiryDialog} onLogin={handleLogout} />
{/if}
