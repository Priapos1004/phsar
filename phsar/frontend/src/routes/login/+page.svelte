<script lang="ts">
    import { goto } from '$app/navigation';
    import { page } from '$app/state';
    import { token } from '$lib/stores/auth';
    import { fly } from 'svelte/transition';
    import { api, ApiError } from '$lib/api';
    import type { TokenResponse } from '$lib/types/api';
    import { describeReturn, safeReturnPath, urlWithNext } from '$lib/utils/returnTo';
    import { landAfterAuth } from '$lib/utils/resumeSession';
    import { Button } from '$lib/components/ui/button';
    import { Input } from '$lib/components/ui/input';
    import { Label } from '$lib/components/ui/label';
    import * as Card from '$lib/components/ui/card';

    let username = $state('');
    let password = $state('');
    let error = $state('');
    let loading = $state(false);

    // Whatever set this — an expired session, a maintenance bounce, or a link
    // someone was sent. `null` simply means "go home after signing in".
    let next = $derived(safeReturnPath(page.url.searchParams.get('next'), page.url.origin));

    async function handleLogin(e: Event) {
        e.preventDefault();
        error = '';
        loading = true;

        try {
            const data = await api.postForm<TokenResponse>(
                '/auth/login',
                new URLSearchParams({ username, password })
            );
            token.set(data.access_token);
            // replaceState so browser-back from the restored page doesn't come
            // back to a login form the user has already passed.
            goto(landAfterAuth(data.access_token, next), { replaceState: true });
        } catch (err) {
            if (err instanceof ApiError) {
                // 503 is the maintenance gate — the global MaintenanceBanner
                // already conveys the state, so the form just stays quiet
                // (no inline error, no double-banner clutter).
                if (err.status !== 503) {
                    error = err.detail;
                }
            } else {
                console.error(err);
                error = 'An unexpected error occurred.';
            }
        } finally {
            loading = false;
        }
    }
</script>

<svelte:head>
	<title>Sign in — Phsar</title>
</svelte:head>

<div class="fixed inset-0 bg-gradient-to-br from-[var(--auth-gradient-from)] via-[var(--auth-gradient-via)] to-[var(--auth-gradient-to)] flex justify-center items-start pt-20">
    <div in:fly={{ y: 20, duration: 2000 }} class="w-full max-w-md">
        <Card.Root>
            <Card.Header>
                <h2 class="text-2xl font-bold text-center text-card-foreground">Login</h2>
            </Card.Header>
            <Card.Content>
                <!-- Named, not generic: a `next` can outlive the user's memory of
                     the link that set it, and a recipient of a shared link has no
                     idea why a login form is what they got. -->
                {#if next}
                    <p class="mb-4 text-center text-sm text-muted-foreground">
                        After signing in you'll be taken to {describeReturn(next)}.
                    </p>
                {/if}
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
                <!-- `next` rides across, so someone who follows a shared link and
                     registers on the spot still lands on what they were sent. -->
                <p class="mt-4 text-center text-sm text-muted-foreground">
                    Have a registration token?
                    <a href={urlWithNext('/register', next)} class="text-primary hover:underline">Register</a>
                </p>
            </Card.Content>
        </Card.Root>
    </div>
</div>
