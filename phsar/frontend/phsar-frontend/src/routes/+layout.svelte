<script lang="ts">
    import { page } from '$app/state';
    import { token } from '$lib/stores/auth';
    import { onMount } from 'svelte';
    import { jwtDecode } from 'jwt-decode';
    import '../app.css';

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
        
        <!-- CLICKABLE BANNER -->
        <a href="/" class="banner-link">
            <header class="banner">
                <img src="/phsar_logo_transparent.png" alt="Phsar Logo" class="banner-logo" />
                <h1 class="banner-title">Private Hot Shit Anime Rating</h1>
                <img src="/phsar_logo_transparent.png" alt="Phsar Logo" class="banner-logo" />
            </header>
        </a>

        <!-- NAVIGATION -->
        <nav>
            <div class="nav-left">
                <a href="/search" class="nav-link">
                    <span>Search</span>
                </a>
                <a href="/ratings" class="nav-link">
                    <span>Ratings</span>
                </a>
                <a href="/watchlist" class="nav-link">
                    <span>Watchlist</span>
                </a>
                <a href="/dashboard" class="nav-link">
                    <span>Dashboard</span>
                </a>
                {#if isAdmin}
                    <a href="/admin-dashboard" class="nav-link">
                        <span>Admin</span>
                    </a>
                {/if}
            </div>
            {#if isAuthenticated}
                <div class="nav-right">
                    <a href="/user" class="nav-icon-link user-icon-wrapper">
                        <img src="/icons/user_icon_transparent.png" alt="User" class="nav-icon" />
                    </a>
                    <button class="nav-icon-btn logout-icon-wrapper" on:click={() => {
                        token.set(null);
                        window.location.href = '/login';
                    }}>
                        <img src="/icons/logout_icon_transparent.png" alt="Logout" class="nav-icon" />
                    </button>
                </div>
            {/if}
        </nav>
    {/if}

    <main>
        <slot />
    </main>
{/if}

<style>
    /* BANNER STYLES */
    .banner-link {
        text-decoration: none;
        display: block;
    }

    .banner {
        display: flex;
        align-items: flex-end;
        justify-content: center;
        background-color: var(--color-banner);
        color: var(--color-banner-text);
        padding: 1rem 2rem;
        gap: 1rem;
        border-bottom: 2px solid var(--color-banner-border-bottom);
        text-align: center;
        transition: background-color 0.2s ease;
    }

    .banner:hover {
        background-color: var(--color-banner-hover);
        cursor: pointer;
    }

    .banner-logo {
        height: 60px;
        width: auto;
    }

    .banner-title {
        font-size: 2rem;
        font-weight: bold;
        margin: 0;
        flex: 1 1 auto;
        word-break: break-word;
    }

    /* Responsive tweaks */
    @media (max-width: 768px) {
        .banner-logo { height: 45px; }
        .banner-title { font-size: 1.7rem; }
    }

    @media (max-width: 500px) {
        .banner { padding: 0.5rem 1rem; gap: 0.5rem; }
        .banner-logo { height: 35px; }
        .banner-title { font-size: 1.3rem; }
    }

    /* NAV STYLES */
    nav {
        display: flex;
        justify-content: space-between;
        align-items: center;
        padding: 1rem 2rem;
        background: var(--color-banner);
        border-bottom: 2px solid var(--color-banner-border-bottom);
        box-shadow: 0 2px 4px rgba(0, 0, 0, 0.3);
    }

    .nav-left {
        display: flex;
        gap: 2rem;
        align-items: center;
    }

    .nav-link {
        display: flex;
        align-items: center;
        text-decoration: none;
        color: var(--color-nav-link);
        font-size: 1.1rem;
        font-weight: 600;
        transition: color 0.2s ease, transform 0.2s ease;
    }

    .nav-link:hover {
        color: var(--color-nav-link-hover);
        transform: scale(1.05);
    }

    .nav-right {
        display: flex;
        align-items: center;
        gap: 1rem;
    }

    .nav-icon-link,
    .nav-icon-btn {
        display: flex;
        align-items: center;
        justify-content: center;
        padding: 0;
        border: none;
        background: transparent;
        cursor: pointer;
        height: 40px;
        width: 40px;
        transition: transform 0.2s ease;
    }

    /* Hover zoom */
    .nav-icon-link:hover,
    .nav-icon-btn:hover {
        transform: scale(1.1);
    }

    .nav-icon {
        height: 40px;
        width: auto;
        max-width: 100%;
        transition: all 0.2s ease;
    }

    /* Image swap on hover */
    .user-icon-wrapper:hover .nav-icon {
        content: url('/icons/user_icon_hover_transparent.png');
    }
    .logout-icon-wrapper:hover .nav-icon {
        content: url('/icons/logout_icon_hover_transparent.png');
    }

    main {
        padding: 0;
        margin: 0;
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
