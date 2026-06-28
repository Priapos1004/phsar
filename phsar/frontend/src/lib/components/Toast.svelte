<script lang="ts">
    import { fly } from 'svelte/transition';
    import type { ToastVariant } from '$lib/stores/toast';

    interface Props {
        message: string;
        show: boolean;
        variant?: ToastVariant;
    }

    let { message, show, variant = 'info' }: Props = $props();

    // info is the default neutral/primary banner for plain confirmations
    // ("Settings updated", "Copied to clipboard", "Backup queued"); success /
    // error give the bell's completion toasts their green/red read. success
    // uses a literal emerald (not a themed token) deliberately — there's no
    // `--success` in the theme system, and emerald is already the app's
    // de-facto "success/complete" green (Story Complete badge, bell status
    // icon); error reuses the themed `destructive` token since one exists.
    const VARIANT_CLASS: Record<ToastVariant, string> = {
        info: 'bg-primary text-primary-foreground',
        success: 'bg-emerald-600 text-white',
        error: 'bg-destructive text-destructive-foreground',
    };
</script>

{#if show}
    <div
        class="fixed top-20 left-1/2 -translate-x-1/2 z-50 px-4 py-2 rounded-lg shadow-lg text-sm font-medium {VARIANT_CLASS[variant]}"
        in:fly={{ y: -20, duration: 200 }}
        out:fly={{ y: -20, duration: 150 }}
    >
        {message}
    </div>
{/if}
