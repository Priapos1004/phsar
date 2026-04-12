<script lang="ts">
    import { goto } from '$app/navigation';
    import { api, ApiError } from '$lib/api';
    import { token } from '$lib/stores/auth';
    import { userSettings } from '$lib/stores/userSettings';
    import * as Card from '$lib/components/ui/card';
    import * as Dialog from '$lib/components/ui/dialog';
    import { Button } from '$lib/components/ui/button';
    import { Input } from '$lib/components/ui/input';
    import { Label } from '$lib/components/ui/label';
    import { Lock, Unlock, Trash2 } from 'lucide-svelte';

    interface Props {
        isRestricted?: boolean;
    }

    let { isRestricted = false }: Props = $props();

    const CRACKS_TO_BREAK = 5;

    let crackLevel = $state(0);
    let shattering = $state(false);
    let broken = $state(false);
    let shaking = $state(false);

    // Delete flow
    let showConfirm = $state(false);
    let password = $state('');
    let deleting = $state(false);
    let deleteError = $state('');

    // Farewell dialog
    let showFarewell = $state(false);

    // Glass shards — irregular polygons that tile the glass surface.
    // Each shard: clip-path polygon (%) + fly direction (px) + rotation (deg).
    const shards: { clip: string; tx: number; ty: number; rot: number; delay: number }[] = [
        // Top-left region
        { clip: 'polygon(0% 0%, 30% 0%, 25% 20%, 10% 25%, 0% 15%)', tx: -120, ty: -80, rot: -25, delay: 0 },
        { clip: 'polygon(30% 0%, 55% 0%, 50% 15%, 25% 20%)', tx: -40, ty: -100, rot: 15, delay: 30 },
        // Top-right region
        { clip: 'polygon(55% 0%, 80% 0%, 100% 0%, 100% 20%, 75% 25%, 50% 15%)', tx: 100, ty: -90, rot: 20, delay: 10 },
        // Left side
        { clip: 'polygon(0% 15%, 10% 25%, 25% 20%, 35% 45%, 20% 55%, 0% 50%)', tx: -130, ty: 20, rot: -30, delay: 50 },
        // Center-left
        { clip: 'polygon(25% 20%, 50% 15%, 55% 45%, 35% 45%)', tx: -60, ty: -40, rot: 12, delay: 20 },
        // Center-right
        { clip: 'polygon(50% 15%, 75% 25%, 70% 50%, 55% 45%)', tx: 50, ty: -30, rot: -18, delay: 40 },
        // Right side
        { clip: 'polygon(75% 25%, 100% 20%, 100% 55%, 80% 60%, 70% 50%)', tx: 140, ty: 10, rot: 25, delay: 15 },
        // Bottom-left
        { clip: 'polygon(0% 50%, 20% 55%, 35% 45%, 40% 70%, 25% 80%, 0% 100%, 0% 75%)', tx: -110, ty: 80, rot: -20, delay: 35 },
        // Bottom-center
        { clip: 'polygon(35% 45%, 55% 45%, 70% 50%, 65% 75%, 40% 100%, 25% 100%, 25% 80%, 40% 70%)', tx: 10, ty: 100, rot: 8, delay: 25 },
        // Bottom-right
        { clip: 'polygon(70% 50%, 80% 60%, 100% 55%, 100% 100%, 40% 100%, 65% 75%)', tx: 120, ty: 70, rot: -15, delay: 45 },
    ];

    function handleGlassClick() {
        if (broken || shattering) return;

        crackLevel++;
        shaking = true;
        setTimeout(() => (shaking = false), 300);

        if (crackLevel >= CRACKS_TO_BREAK) {
            shattering = true;
            setTimeout(() => {
                shattering = false;
                broken = true;
            }, 700);
        }
    }

    function openConfirm() {
        password = '';
        deleteError = '';
        showConfirm = true;
    }

    async function handleDelete() {
        deleting = true;
        deleteError = '';
        try {
            await api.del('/users/account', { password });
            showConfirm = false;
            showFarewell = true;
        } catch (err) {
            deleteError = err instanceof ApiError ? err.detail : 'Failed to delete account.';
        } finally {
            deleting = false;
        }
    }

    function handleFarewellClose() {
        token.set(null);
        userSettings.set(null);
        goto('/login');
    }

    // SVG crack paths — each level adds more cracks
    const crackPaths: string[][] = [
        ['M 50 0 L 45 25 L 55 50 L 48 75 L 52 100'],
        ['M 0 35 L 20 40 L 45 38', 'M 55 50 L 75 45 L 100 50'],
        ['M 30 0 L 35 20 L 25 35', 'M 70 100 L 65 80 L 72 60'],
        ['M 0 70 L 25 65 L 48 75', 'M 100 20 L 80 25 L 55 20', 'M 40 50 L 30 55 L 20 50'],
        ['M 10 0 L 15 15', 'M 90 0 L 85 20', 'M 0 90 L 15 85', 'M 100 80 L 85 75', 'M 45 40 L 50 45 L 55 40'],
    ];
</script>

<Card.Root class="relative overflow-hidden border-destructive/40">
    <Card.Header>
        <h2 class="text-lg font-semibold text-destructive">Danger Zone</h2>
    </Card.Header>

    <!-- Intact glass overlay -->
    {#if !broken && !shattering}
        <button
            class="glass-base glass-overlay absolute inset-0 z-10 rounded-[inherit] cursor-pointer
                   flex flex-col items-center justify-center gap-2
                   {shaking ? 'animate-shake' : ''}"
            onclick={handleGlassClick}
            aria-label="Click to unlock danger zone ({CRACKS_TO_BREAK - crackLevel} clicks remaining)"
        >
            <svg
                class="absolute inset-0 w-full h-full pointer-events-none"
                viewBox="0 0 100 100"
                preserveAspectRatio="none"
            >
                {#each { length: crackLevel } as _, i}
                    {#each crackPaths[i] as path}
                        <path d={path} fill="none" stroke="rgba(0,0,0,0.25)" stroke-width="0.6" stroke-linecap="round" />
                        <path d={path} fill="none" stroke="rgba(255,255,255,0.9)" stroke-width="0.4" stroke-linecap="round" transform="translate(0.4, 0.4)" />
                    {/each}
                {/each}
            </svg>

            {#if crackLevel === 0}
                <Lock class="size-6 text-card-foreground/50" />
                <span class="text-sm text-card-foreground/50 font-medium">Click to unlock</span>
            {:else}
                <Unlock class="size-6 text-card-foreground/40" />
                <span class="text-xs text-card-foreground/40">
                    {CRACKS_TO_BREAK - crackLevel} {CRACKS_TO_BREAK - crackLevel === 1 ? 'click' : 'clicks'} remaining
                </span>
            {/if}
        </button>
    {/if}

    <!-- Shattering shards — glass breaks into pieces flying outward -->
    {#if shattering}
        {#each shards as shard}
            <div
                class="glass-base glass-shard absolute inset-0 z-10 pointer-events-none"
                style="
                    clip-path: {shard.clip};
                    --shard-tx: {shard.tx}px;
                    --shard-ty: {shard.ty}px;
                    --shard-rot: {shard.rot}deg;
                    animation-delay: {shard.delay}ms;
                "
            ></div>
        {/each}
    {/if}

    <Card.Content>
        <div class="space-y-3 {!broken ? 'select-none' : ''}">
            <p class="text-sm text-muted-foreground">
                Permanently delete your account and all associated data. This action cannot be undone.
            </p>
            <Button
                variant="destructive"
                onclick={openConfirm}
                disabled={!broken || isRestricted}
            >
                <Trash2 class="size-4 mr-2" />
                Delete Account
            </Button>
            {#if isRestricted}
                <p class="text-xs text-muted-foreground">You don't have permission to delete your account.</p>
            {/if}
        </div>
    </Card.Content>
</Card.Root>

<!-- Confirmation dialog -->
<Dialog.Root bind:open={showConfirm}>
    <Dialog.Content class="sm:max-w-md">
        <Dialog.Header>
            <Dialog.Title class="text-destructive">Delete Account</Dialog.Title>
            <Dialog.Description>
                This will permanently delete your account, ratings, watchlist, and all associated data. Enter your password to confirm.
            </Dialog.Description>
        </Dialog.Header>
        <div class="space-y-4 py-2">
            <div class="space-y-2">
                <Label for="delete-password">Password</Label>
                <Input
                    id="delete-password"
                    type="password"
                    bind:value={password}
                    placeholder="Enter your password"
                    onkeydown={(e: KeyboardEvent) => { if (e.key === 'Enter' && password && !deleting) handleDelete(); }}
                />
            </div>
            {#if deleteError}
                <p class="text-destructive text-sm">{deleteError}</p>
            {/if}
        </div>
        <Dialog.Footer>
            <Button variant="secondary" onclick={() => (showConfirm = false)} disabled={deleting}>
                Cancel
            </Button>
            <Button
                variant="destructive"
                onclick={handleDelete}
                disabled={!password || deleting}
            >
                {deleting ? 'Deleting...' : 'Delete my account'}
            </Button>
        </Dialog.Footer>
    </Dialog.Content>
</Dialog.Root>

<!-- Farewell dialog (non-dismissible, like token expiry) -->
<Dialog.Root bind:open={showFarewell}>
    <Dialog.Content
        class="sm:max-w-md"
        showCloseButton={false}
        onInteractOutside={(e) => e.preventDefault()}
        onEscapeKeydown={(e) => e.preventDefault()}
    >
        <Dialog.Header>
            <Dialog.Title>Account Deleted</Dialog.Title>
            <Dialog.Description>
                Thank you for using PHSAR. We're sorry to see you go — your account and all
                associated data have been permanently removed. If you ever want to come back,
                you're always welcome.
            </Dialog.Description>
        </Dialog.Header>
        <Dialog.Footer>
            <Button onclick={handleFarewellClose} class="w-full">Continue to login</Button>
        </Dialog.Footer>
    </Dialog.Content>
</Dialog.Root>

<style>
    .glass-base {
        background:
            linear-gradient(
                135deg,
                transparent 25%,
                rgba(255, 255, 255, 0.25) 35%,
                rgba(255, 255, 255, 0.35) 45%,
                transparent 55%
            ),
            linear-gradient(
                180deg,
                rgba(180, 200, 220, 0.35) 0%,
                rgba(160, 180, 200, 0.25) 100%
            );
        backdrop-filter: blur(2px);
    }

    .glass-overlay {
        box-shadow:
            inset 0 1px 0 rgba(255, 255, 255, 0.4),
            inset 0 -1px 0 rgba(0, 0, 0, 0.05),
            0 1px 3px rgba(0, 0, 0, 0.06);
    }

    .glass-overlay:hover {
        background:
            linear-gradient(
                135deg,
                transparent 25%,
                rgba(255, 255, 255, 0.3) 35%,
                rgba(255, 255, 255, 0.4) 45%,
                transparent 55%
            ),
            linear-gradient(
                180deg,
                rgba(180, 200, 220, 0.4) 0%,
                rgba(160, 180, 200, 0.3) 100%
            );
    }

    .glass-shard {
        animation: shard-fly 600ms ease-out forwards;
    }

    @keyframes shard-fly {
        0% {
            transform: translate(0, 0) rotate(0deg);
            opacity: 1;
        }
        100% {
            transform: translate(var(--shard-tx), var(--shard-ty)) rotate(var(--shard-rot));
            opacity: 0;
        }
    }

    @keyframes shake {
        0%, 100% { transform: translateX(0); }
        15% { transform: translateX(-3px) rotate(-0.5deg); }
        30% { transform: translateX(3px) rotate(0.5deg); }
        45% { transform: translateX(-2px) rotate(-0.3deg); }
        60% { transform: translateX(2px) rotate(0.3deg); }
        75% { transform: translateX(-1px); }
    }

    :global(.animate-shake) {
        animation: shake 0.3s ease-in-out;
    }
</style>
