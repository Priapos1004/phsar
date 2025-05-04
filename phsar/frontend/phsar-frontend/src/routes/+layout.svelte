<script lang="ts">
    import { page } from '$app/state';
    import { token } from '$lib/stores/auth';
    import { onMount } from 'svelte';
    import { jwtDecode } from 'jwt-decode';

    let loading = true;
    let isAuthenticated = false;
    let isAdmin = false;

    interface DecodedToken {
        sub: string;
        role: string;
        exp: number;
    }

    onMount(() => {
        const unsubscribe = token.subscribe((val) => {
            isAuthenticated = !!val;
            if (val) {
                const decoded = jwtDecode<DecodedToken>(val);
                isAdmin = decoded.role === 'admin';
            } else {
                isAdmin = false;
            }
            loading = false;
        });

        return unsubscribe;
    });
</script>

{#if loading}
    <div class="loading-screen">Loading...</div>
{:else}
    {#if page.url.pathname !== '/login'}
        <nav>
            <div class="nav-left">
                <a href="/">🏠 Home</a>
                <a href="/dashboard">📊 Dashboard</a>
                {#if isAdmin}
                    <a href="/admin-dashboard">🔒 Admin</a>
                {/if}
            </div>
            {#if isAuthenticated}
                <button class="logout-btn" on:click={() => {
                    token.set(null);
                    window.location.href = '/login';
                }}>
                    🚪 Logout
                </button>
            {/if}
        </nav>
    {/if}

    <main>
        <slot />
    </main>
{/if}

<style>
    nav {
        display: flex;
        justify-content: space-between;
        align-items: center;
        padding: 1rem 2rem;
        background: #f5f5f5;
        border-bottom: 1px solid #ddd;
        box-shadow: 0 2px 4px rgba(0, 0, 0, 0.05);
    }

    .nav-left {
        display: flex;
        gap: 1.5rem;
        align-items: center;
    }

    nav a {
        text-decoration: none;
        color: #333;
        font-weight: 500;
        transition: color 0.2s ease;
    }

    nav a:hover {
        color: #0070f3;
    }

    .logout-btn {
        padding: 0.5rem 1rem;
        border: none;
        background: #0070f3;
        color: white;
        border-radius: 4px;
        cursor: pointer;
        font-weight: 500;
        transition: background 0.2s ease;
    }

    .logout-btn:hover {
        background: #005bb5;
    }

    main {
        padding: 2rem;
    }

    .loading-screen {
        display: flex;
        justify-content: center;
        align-items: center;
        min-height: 100vh;
        font-size: 1.5rem;
        color: #555;
    }
</style>