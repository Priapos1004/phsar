<script lang="ts">
    import { page } from '$app/state';
    import { get } from 'svelte/store';
    import { token } from '$lib/stores/auth';
    import { userSettings } from '$lib/stores/userSettings';
    import { spoilerVisibility, refreshSpoilerVisibility } from '$lib/stores/spoilerVisibility';
    import { onMount, setContext } from 'svelte';
    import { jwtDecode } from 'jwt-decode';
    import { api } from '$lib/api';
    import NavBar from '$lib/components/NavBar.svelte';
    import MaintenanceBanner from '$lib/components/MaintenanceBanner.svelte';
    import SessionTimeoutBanner from '$lib/components/SessionTimeoutBanner.svelte';
    import TokenExpiryDialog from '$lib/components/TokenExpiryDialog.svelte';
    import LoadingScreen from '$lib/components/LoadingScreen.svelte';
    import VersionFooter from '$lib/components/VersionFooter.svelte';
    import ToastHost from '$lib/components/ToastHost.svelte';
    import { getThemeCssClass, isValidTheme } from '$lib/themes';
    import '../app.css';
    import type { Snippet } from 'svelte';
    import type { UserSettings } from '$lib/types/api';

    let { children }: { children: Snippet } = $props();

    let loading = $state(true);
    let signingOut = $state(false);
    let isAuthenticated = $state(false);
    let userRole = $state<string | null>(null);
    let username = $state<string | null>(null);
    let showExpiryDialog = $state(false);

    setContext('userRole', () => userRole);
    setContext('username', () => username);

    interface DecodedToken {
      sub: string;
      role: string;
    }

    onMount(() => {
      const unsubscribe = token.subscribe(async (val) => {
        // A fresh token (login OR a silent slide refresh) dismisses any stale
        // "Session Expired" dialog. Expiry itself is now owned by
        // SessionTimeoutBanner's 1s tick — no setTimeout here.
        showExpiryDialog = false;
        isAuthenticated = !!val;
        if (val) {
          try {
            const decoded = jwtDecode<DecodedToken>(val);
            // The sliding session re-issues the SAME user's token every few
            // minutes — only (re)fetch settings + spoiler visibility on a real
            // login / user switch (sub changed) or after a prior failed load,
            // not on every slide, to avoid redundant traffic + a theme flicker.
            const needsUserLoad = decoded.sub !== username || get(userSettings) === null;
            userRole = decoded.role;
            username = decoded.sub;

            if (needsUserLoad) {
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
      };
    });

    // Apply theme CSS class to <html> and sync to localStorage for FOUC prevention.
    // Must be on <html> (not <body>) so overrides sit at the same :root level
    // where @theme inline defines the CSS custom properties.
    //
    // Guarded on `$userSettings !== null`: while settings are still loading we must
    // NOT touch the class list, or we'd wipe whatever the FOUC script in app.html
    // pre-applied — leaving the loading screen (and any pre-hydration paint) on the
    // default purple instead of the user's theme color.
    $effect(() => {
      if (!$userSettings) return;
      const themeKey = $userSettings.theme;
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

    async function handleLogout() {
      signingOut = true;
      token.set(null);
      // Brief themed farewell — the sakura-ring screen acts as a soft transition
      // from the authenticated app back to /login instead of an abrupt hard nav.
      await new Promise(resolve => setTimeout(resolve, 1500));
      window.location.href = '/login';
    }
</script>

{#if loading || signingOut}
    <LoadingScreen />
{:else}
    <!-- Banner sits above the navbar so it's the first thing users see on
         every page (including /login and /register). It only renders when
         the backend reports a scheduled or active maintenance window.
         Single sticky container wraps both so the banner doesn't scroll
         off the top while the navbar stays pinned. -->
    <div class="sticky top-0 z-50">
      <!-- Idle-timeout warning sits above maintenance — a "you're about to be
           signed out" countdown is more urgent than a future-window notice.
           Only runs while authenticated and off the auth pages. -->
      {#if isAuthenticated && page.url.pathname !== '/login' && page.url.pathname !== '/register'}
        <SessionTimeoutBanner onExpire={() => (showExpiryDialog = true)} />
      {/if}
      <MaintenanceBanner />
      {#if page.url.pathname !== '/login' && page.url.pathname !== '/register'}
        <NavBar
          {isAuthenticated}
          {username}
          isAdmin={userRole === 'admin'}
          onLogout={handleLogout}
        />
      {/if}
    </div>

    <main class="min-h-screen px-8 pt-4 pb-8">
      {@render children()}
    </main>

    <VersionFooter />

    <!-- Single global toast slot — the navbar JobBell fires completion toasts
         through it (pushToast), and /library/add routes its enqueue toast here
         too so the two never overlap. -->
    <ToastHost />

    <TokenExpiryDialog open={showExpiryDialog} onLogin={handleLogout} />
{/if}
