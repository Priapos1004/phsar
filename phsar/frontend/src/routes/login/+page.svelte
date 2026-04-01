<script lang="ts">
    import { goto } from '$app/navigation';
    import { token } from '$lib/stores/auth';
    import { API_URL } from '$lib/config';
    import { fly } from 'svelte/transition';
    import { Button } from '$lib/components/ui/button';
    import { Input } from '$lib/components/ui/input';
    import { Label } from '$lib/components/ui/label';
    import * as Card from '$lib/components/ui/card';

    let username = $state('');
    let password = $state('');
    let error = $state('');
    let loading = $state(false);

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
    <div in:fly={{ y: 20, duration: 2000 }} class="w-full max-w-md">
        <Card.Root>
            <Card.Header>
                <h2 class="text-2xl font-bold text-center text-card-foreground">Login</h2>
            </Card.Header>
            <Card.Content>
                <form onsubmit={handleLogin} class="space-y-4">
                    <div class="space-y-2">
                        <Label for="username">Username</Label>
                        <Input
                            id="username"
                            type="text"
                            bind:value={username}
                            required
                            class="h-10"
                        />
                    </div>
                    <div class="space-y-2">
                        <Label for="password">Password</Label>
                        <Input
                            id="password"
                            type="password"
                            bind:value={password}
                            required
                            class="h-10"
                        />
                    </div>
                    <Button
                        type="submit"
                        disabled={loading}
                        class="w-full"
                        size="lg"
                    >
                        {#if loading}
                            Logging in...
                        {:else}
                            Login
                        {/if}
                    </Button>
                </form>
                {#if error}
                    <div class="mt-4 text-center text-destructive text-sm">{error}</div>
                {/if}
            </Card.Content>
        </Card.Root>
    </div>
</div>
