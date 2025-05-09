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
                body: new URLSearchParams({ username, password })
            });

            if (!response.ok) {
                const data = await response.json();
                error = data.detail || 'Login failed';
                return;
            }

            const data = await response.json();
            token.set(data.access_token);
            goto('/');
        } catch (err) {
            console.error(err);
            error = 'An unexpected error occurred.';
        } finally {
            loading = false;
        }
    }
</script>

<div class="fixed inset-0 bg-gradient-to-br from-purple-300 via-purple-500 to-purple-800 flex justify-center items-start pt-20">
    <div class="w-full max-w-md bg-white rounded-lg shadow-lg p-8">
        <h2 class="text-2xl font-bold mb-6 text-center text-gray-800">Login</h2>
        <form on:submit|preventDefault={handleLogin} class="space-y-4">
            <div>
                <label for="username" class="block text-sm font-medium text-gray-700">Username</label>
                <input 
                    id="username"
                    type="text"
                    bind:value={username}
                    required
                    class="mt-1 block w-full px-3 py-2 border border-gray-300 rounded-md shadow-sm text-gray-900 focus:outline-none focus:ring-purple-500 focus:border-purple-500"
                />
            </div>
            <div>
                <label for="password" class="block text-sm font-medium text-gray-700">Password</label>
                <input 
                    id="password"
                    type="password"
                    bind:value={password}
                    required
                    class="mt-1 block w-full px-3 py-2 border border-gray-300 rounded-md shadow-sm text-gray-900 focus:outline-none focus:ring-purple-500 focus:border-purple-500"
                />
            </div>
            <button
                type="submit"
                disabled={loading}
                class="w-full py-2 px-4 bg-purple-700 text-white font-semibold rounded-md shadow hover:bg-purple-600 transition disabled:opacity-50"
            >
                {#if loading}
                    Logging in...
                {:else}
                    Login
                {/if}
            </button>
        </form>
        {#if error}
            <div class="mt-4 text-center text-red-600 text-sm">{error}</div>
        {/if}
    </div>
</div>
