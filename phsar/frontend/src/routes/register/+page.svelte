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

    const USERNAME_PATTERN = /^[a-zA-Z0-9_-]+$/;
    const USERNAME_MIN = 3;
    const USERNAME_MAX = 32;
    const PASSWORD_MIN = 8;
    const PASSWORD_MAX = 128;

    let registrationToken = $state('');
    let username = $state('');
    let password = $state('');
    let confirmPassword = $state('');
    let error = $state('');
    let loading = $state(false);

    // Inline validation — only show after user has started typing
    let usernameError = $derived.by(() => {
        if (!username) return '';
        if (username.length < USERNAME_MIN) return `At least ${USERNAME_MIN} characters`;
        if (username.length > USERNAME_MAX) return `At most ${USERNAME_MAX} characters`;
        if (!USERNAME_PATTERN.test(username)) return 'Letters, numbers, underscores, and hyphens only';
        return '';
    });

    let passwordError = $derived.by(() => {
        if (!password) return '';
        if (password.length < PASSWORD_MIN) return `At least ${PASSWORD_MIN} characters`;
        if (password.length > PASSWORD_MAX) return `At most ${PASSWORD_MAX} characters`;
        return '';
    });

    let passwordMismatch = $derived(confirmPassword !== '' && password !== confirmPassword);

    let hasValidationErrors = $derived(
        !!usernameError || !!passwordError || passwordMismatch
        || !registrationToken || !username || !password || !confirmPassword
    );

    async function handleRegister(e: Event) {
        e.preventDefault();
        error = '';

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

<div class="fixed inset-0 bg-gradient-to-br from-[var(--auth-gradient-from)] via-[var(--auth-gradient-via)] to-[var(--auth-gradient-to)] flex justify-center items-start pt-20">
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
                            aria-invalid={!!usernameError || undefined}
                            maxlength={USERNAME_MAX}
                        />
                        {#if usernameError}
                            <p class="text-xs text-destructive">{usernameError}</p>
                        {/if}
                    </div>
                    <div class="space-y-2">
                        <Label for="password">Password</Label>
                        <Input
                            id="password"
                            type="password"
                            bind:value={password}
                            required
                            class="h-10"
                            aria-invalid={!!passwordError || undefined}
                            maxlength={PASSWORD_MAX}
                        />
                        {#if passwordError}
                            <p class="text-xs text-destructive">{passwordError}</p>
                        {/if}
                    </div>
                    <div class="space-y-2">
                        <Label for="confirm-password">Confirm Password</Label>
                        <Input
                            id="confirm-password"
                            type="password"
                            bind:value={confirmPassword}
                            required
                            class="h-10"
                            aria-invalid={!!passwordMismatch || undefined}
                            maxlength={PASSWORD_MAX}
                        />
                        {#if passwordMismatch}
                            <p class="text-xs text-destructive">Passwords do not match</p>
                        {/if}
                    </div>
                    <Button
                        type="submit"
                        disabled={loading || hasValidationErrors}
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
