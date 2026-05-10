<script lang="ts">
    /**
     * Shared yellow info/warning banner — used by the global maintenance
     * countdown and inline notices on /login. Stays a contained
     * rounded-card so a full-width edge-to-edge bar (which reads as
     * alarming) is no longer the default look.
     */
    import { AlertTriangle } from 'lucide-svelte';
    import type { Snippet } from 'svelte';

    let { children }: { children: Snippet } = $props();
</script>

<div
    role="status"
    class="flex items-start gap-2 rounded-md border border-yellow-200 bg-yellow-50 px-3 py-2 text-sm text-yellow-900"
>
    <AlertTriangle class="w-4 h-4 shrink-0 mt-0.5" />
    <span>{@render children()}</span>
</div>
