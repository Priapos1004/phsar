<script lang="ts">
    import * as Dialog from '$lib/components/ui/dialog';
    import { Button } from '$lib/components/ui/button';

    interface Props {
        open: boolean;
        onLogin: () => void;
    }

    let { open, onLogin }: Props = $props();
</script>

<Dialog.Root bind:open>
    <Dialog.Content
        class="sm:max-w-md bg-pink-100 text-card-foreground border border-pink-700"
        showCloseButton={false}
        onInteractOutside={(e) => e.preventDefault()}
        onEscapeKeydown={(e) => e.preventDefault()}
    >
        <Dialog.Header>
            <Dialog.Title>Session Expired</Dialog.Title>
            <Dialog.Description>
                Your session has expired. Please log in again to continue.
            </Dialog.Description>
        </Dialog.Header>
        <Dialog.Footer>
            <Button onclick={onLogin} class="w-full">Log in</Button>
        </Dialog.Footer>
    </Dialog.Content>
</Dialog.Root>
