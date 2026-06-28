<script lang="ts">
    import { activeToast } from '$lib/stores/toast';
    import Toast from './Toast.svelte';

    // Mounted once in the root layout so any component (notably the global
    // JobBell) can fire a toast via pushToast() without owning its own banner.
    //
    // {#key activeToast.id} re-creates the Toast whenever a NEW toast is pushed,
    // so a second toast arriving mid-display replays the fly-in (the old one
    // animates out, the new one in) instead of silently swapping text. When the
    // store clears to null the {#if} removes the Toast and its out:fly plays.
</script>

{#if $activeToast}
    {#key $activeToast.id}
        <Toast message={$activeToast.message} variant={$activeToast.variant} show />
    {/key}
{/if}
