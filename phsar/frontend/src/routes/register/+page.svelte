<script lang="ts">
    import { goto } from '$app/navigation';
    import { token } from '$lib/stores/auth';
    import { fly } from 'svelte/transition';
    import { api, ApiError } from '$lib/api';
    import type { TokenResponse } from '$lib/types/api';
    import { Button } from '$lib/components/ui/button';
    import { Input } from '$lib/components/ui/input';
    import { Label } from '$lib/components/ui/label';
    import * as Card from '$lib/components/ui/card';

    let registrationToken = $state('');
    let username = $state('');
    let password = $state('');
    let confirmPassword = $state('');
    let error = $state('');
    let loading = $state(false);

    let passwordMismatch = $derived(confirmPassword !== '' && password !== confirmPassword);

    async function handleRegister(e: Event) {
        e.preventDefault();
        error = '';

        if (password !== confirmPassword) {
            error = 'Passwords do not match.';
            return;
        }

        loading = true;
        try {
            const data = await api.post<TokenResponse>('/auth/register', {
                registration_token: registrationToken,
                username,
                password,
            });
            token.set(data.access_token);
            goto('/');
        } catch (err) {
            if (err instanceof ApiError) {
                error = err.detail;
            } else {
                console.error(err);
                error = 'An unexpected error occurred.';
            }
        } finally {
            loading = false;
        }
    }
</script>

<div class="fixed inset-0 bg-gradient-to-br from-purple-300 via-purple-500 to-purple-800 flex justify-center items-start pt-20">
    <div in:fly={{ y: 20, duration: 2000 }} class="w-full max-w-md">
        <Card.Root>
            <Card.Header>
                <h2 class="text-2xl font-bold text-center text-card-foreground">Register</h2>
            </Card.Header>
            <Card.Content>
                <form onsubmit={handleRegister} class="space-y-4">
                    <div class="space-y-2">
                        <Label for="registration-token">Registration Token</Label>
                        <Input
                            id="registration-token"
                            type="text"
                            bind:value={registrationToken}
                            required
                            class="h-10"
                            placeholder="Paste your registration token"
                        />
                    </div>
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
                    <div class="space-y-2">
                        <Label for="confirm-password">Confirm Password</Label>
                        <Input
                            id="confirm-password"
                            type="password"
                            bind:value={confirmPassword}
                            required
                            class="h-10 {passwordMismatch ? 'border-destructive' : ''}"
                        />
                        {#if passwordMismatch}
                            <p class="text-xs text-destructive">Passwords do not match</p>
                        {/if}
                    </div>
                    <Button
                        type="submit"
                        disabled={loading || passwordMismatch}
                        class="w-full"
                        size="lg"
                    >
                        {#if loading}
                            Registering...
                        {:else}
                            Register
                        {/if}
                    </Button>
                </form>
                {#if error}
                    <div class="mt-4 text-center text-destructive text-sm">{error}</div>
                {/if}
                <p class="mt-4 text-center text-sm text-muted-foreground">
                    Already have an account? <a href="/login" class="text-primary hover:underline">Login</a>
                </p>
            </Card.Content>
        </Card.Root>
    </div>
</div>
