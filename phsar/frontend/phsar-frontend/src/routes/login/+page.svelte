<script lang="ts">
    import { goto } from '$app/navigation';
    import { token } from '$lib/stores/auth';
    import { API_URL } from '$lib/config';

    let username: string = '';
    let password: string = '';
    let error: string = '';
    let loading: boolean = false;

    async function handleLogin() {
        error = '';
        loading = true;

        try {
        const response = await fetch(`${API_URL}/auth/login`, {
            method: 'POST',
            headers: { 'Content-Type': 'application/x-www-form-urlencoded' },
            body: new URLSearchParams({
            username,
            password
            })
        });

        if (!response.ok) {
            const data = await response.json();
            error = data.detail || 'Login failed';
            return;
        }

        const data = await response.json();
        token.set(data.access_token); // ✅ updates store + localStorage

        goto('/'); // 🚀 redirect after login
        } catch (err) {
        console.error(err);
        error = 'An unexpected error occurred.';
        } finally {
        loading = false;
        }
    }
</script>

<style>
    .login-container {
        max-width: 400px;
        margin: 100px auto;
        padding: 2rem;
        border: 1px solid #ddd;
        border-radius: 8px;
        box-shadow: 0 2px 8px rgba(0, 0, 0, 0.1);
    }
    input {
        width: 100%;
        padding: 0.5rem;
        margin-top: 0.5rem;
        margin-bottom: 1rem;
        border-radius: 4px;
        border: 1px solid #ccc;
    }
    button {
        width: 100%;
        padding: 0.75rem;
        background-color: #0070f3;
        color: white;
        border: none;
        border-radius: 4px;
        cursor: pointer;
    }
    button:disabled {
        background-color: #aaa;
    }
    .error {
        color: red;
        margin-top: 1rem;
        text-align: center;
    }
</style>

<div class="login-container">
    <h2>Login</h2>
    <form on:submit|preventDefault={handleLogin}>
        <label>
        Username:
        <input type="text" bind:value={username} required />
        </label>
        <label>
        Password:
        <input type="password" bind:value={password} required />
        </label>
        <button type="submit" disabled={loading}>
        {#if loading}
            Logging in...
        {:else}
            Login
        {/if}
        </button>
    </form>

    {#if error}
        <div class="error">{error}</div>
    {/if}
</div>