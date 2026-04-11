<script lang="ts">
    import { fly } from 'svelte/transition';

    interface Props {
        message: string;
        show: boolean;
    }

    let { message, show }: Props = $props();
</script>

{#if show}
    <div
        class="fixed top-20 left-1/2 -translate-x-1/2 z-50 bg-primary text-primary-foreground px-4 py-2 rounded-lg shadow-lg text-sm font-medium"
        in:fly={{ y: -20, duration: 200 }}
        out:fly={{ y: -20, duration: 150 }}
    >
        {message}
    </div>
{/if}
