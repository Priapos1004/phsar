<script lang="ts">
    import { page } from '$app/state';
    import { token } from '$lib/stores/auth';
    import { onMount } from 'svelte';
    import { jwtDecode } from 'jwt-decode';
    import NavBar from '$lib/components/NavBar.svelte';
    import LoadingScreen from '$lib/components/LoadingScreen.svelte';
    import '../app.css';
    import type { Snippet } from 'svelte';

    let { children }: { children: Snippet } = $props();

    let loading = $state(true);
    let isAuthenticated = $state(false);
    let isAdmin = $state(false);

    interface DecodedToken {
      sub: string;
      role: string;
      exp: number;
    }

    onMount(() => {
      const unsubscribe = token.subscribe((val) => {
        isAuthenticated = !!val;
        if (val) {
          try {
            const decoded = jwtDecode<DecodedToken>(val);
            isAdmin = decoded.role === 'admin';
          } catch {
            token.set(null);
            isAdmin = false;
          }
        } else {
          isAdmin = false;
        }
        loading = false;
      });

      return unsubscribe;
    });

    function handleLogout() {
      token.set(null);
      window.location.href = '/login';
    }
</script>

{#if loading}
    <LoadingScreen />
{:else}
    {#if page.url.pathname !== '/login'}
      <NavBar {isAuthenticated} onLogout={handleLogout} />
    {/if}

    <main class="min-h-screen p-8">
      {@render children()}
    </main>
{/if}
