<script lang="ts">
    import { page } from '$app/state';
    import { get } from 'svelte/store';
    import { token } from '$lib/stores/auth';
    import { userSettings } from '$lib/stores/userSettings';
    import { spoilerVisibility, refreshSpoilerVisibility } from '$lib/stores/spoilerVisibility';
    import { refreshWatchlist, clearWatchlist } from '$lib/stores/watchlist';
    import { refreshTags, clearTags } from '$lib/stores/tags';
    import { clearRatingScores } from '$lib/stores/ratingScores';
    import { clearBrowseRows } from '$lib/stores/browseRows';
  import { clearRatingCoverage } from '$lib/stores/ratingCoverage';
    import { resetAllPersistedFilters } from '$lib/stores/persistedFilter';
    import { applyFilterLifecycle } from '$lib/utils/filterLifecycle';
    import { captureReturnTarget, clearResume } from '$lib/utils/resumeSession';
    import { isAuthPage } from '$lib/utils/returnTo';
    import { afterNavigate } from '$app/navigation';
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
    import * as cls from '$lib/styles/classes';

    let { children }: { children: Snippet } = $props();

    let loading = $state(true);
    let signingOut = $state(false);
    let isAuthenticated = $state(false);
    let userRole = $state<string | null>(null);
    let onAuthPage = $derived(isAuthPage(page.url.pathname));
    let username = $state<string | null>(null);
    let showExpiryDialog = $state(false);

    setContext('userRole', () => userRole);
    setContext('username', () => username);

    // Everything keyed to WHICH user this tab belongs to. The filters join the
    // watchlist/tags pair rather than auth.ts's per-session bell cleanup:
    // `watchlistFilter.tagUuids` holds this user's list uuids, which the next
    // user can't even see. The rating-scores cache is the bluntest case — it
    // holds one user's entire rating set.
    function clearPerUserStores() {
      clearWatchlist();
      clearTags();
      clearRatingScores();
      clearRatingCoverage();
      clearBrowseRows();
      resetAllPersistedFilters();
    }

    // Section filter resets; the rule, and why it can't live in the section
    // layouts, are in utils/filterLifecycle. AFTER the navigation, not before:
    // a section is only ever cleared when the destination is outside it, so no
    // destination reads a store this touches — while clearing beforehand would
    // invalidate the outgoing page's still-mounted derived chain and re-render
    // the whole grid (expanding it back to unfiltered) one tick before it
    // unmounts. `enter` is a first load, not a navigation away from anything.
    afterNavigate(({ type, to }) => {
      if (type !== 'enter' && to) applyFilterLifecycle(to.url.pathname);
    });

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
            const signingIn = decoded.sub !== username;
            const needsUserLoad = signingIn || get(userSettings) === null;
            // A real user switch (A → B) can happen without a null-token transition
            // (login page sets the new token directly), so clear per-user stores here
            // rather than only on logout — else B could inherit A's bookmarks if a
            // refresh is skipped (restricted B) or fails silently.
            const isUserSwitch = signingIn && username !== null;
            userRole = decoded.role;
            username = decoded.sub;

            if (needsUserLoad) {
              if (isUserSwitch) clearPerUserStores();
              // A newly signed-in user's page waits for their loads, as a fresh load
              // already does, so it renders once in their theme and art — not in the
              // default ones first, downloading both pictures.
              if (signingIn) loading = true;
              // Fetch settings + spoiler visibility + watchlist/tags in parallel to
              // avoid serial latency. A restricted user gets none of them: they can't
              // watchlist, and they are pinned to spoiler_level `off` and excluded
              // from the visibility cache, so every one of these 403s. Skipping beats
              // swallowing — a request known to fail shouldn't be sent.
              const userLoads: Promise<unknown>[] =
                decoded.role === 'restricted_user'
                  ? []
                  : [refreshSpoilerVisibility(), refreshWatchlist(), refreshTags()];
              try {
                const [settings] = await Promise.all([
                  api.get<UserSettings>('/users/settings'),
                  ...userLoads,
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
            clearPerUserStores();
          }
        } else {
          userRole = null;
          username = null;
          userSettings.set(null);
          spoilerVisibility.set(null);
          clearPerUserStores();
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
      const toRemove = [...el.classList].filter((name) => name.startsWith('theme-'));
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

    async function farewellThenLeaveTo(target: string) {
      signingOut = true;
      token.set(null);
      // Brief themed farewell — the sakura-ring screen acts as a soft transition
      // from the authenticated app back to /login instead of an abrupt hard nav.
      await new Promise(resolve => setTimeout(resolve, 1500));
      window.location.href = target;
    }

    // Two exits, opposite memories, so they cannot share one handler: a session
    // that lapsed should resume where it stopped, while signing out is a
    // deliberate "done here".
    function handleSessionExpired() {
      void farewellThenLeaveTo(captureReturnTarget(page.url));
    }

    function handleLogout() {
      clearResume();
      void farewellThenLeaveTo('/login');
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
      {#if isAuthenticated && !onAuthPage}
        <SessionTimeoutBanner onExpire={() => (showExpiryDialog = true)} />
      {/if}
      <MaintenanceBanner />
      {#if !onAuthPage}
        <NavBar
          {isAuthenticated}
          {username}
          isAdmin={userRole === 'admin'}
          onLogout={handleLogout}
        />
      {/if}
    </div>

    <!-- No footer on an auth page: below the full-height gradient it would sit on the bare page. -->
    <main class={onAuthPage ? cls.authScreen : `min-h-screen ${cls.pageGutter} pt-4 pb-8`}>
      {@render children()}
    </main>

    {#if !onAuthPage}
      <VersionFooter />
    {/if}

    <!-- Single global toast slot — the navbar JobBell fires completion toasts
         through it (pushToast), and /library/add routes its enqueue toast here
         too so the two never overlap. -->
    <ToastHost />

    <TokenExpiryDialog open={showExpiryDialog} onLogin={handleSessionExpired} />
{/if}
