<script lang="ts">
	/** The type-to-confirm dialog (rules/frontend.md, "A destructive action's confirm is tiered
	 *  by what it costs to undo"). */
	import { getContext, type Snippet } from 'svelte';
	import { Button } from '$lib/components/ui/button';
	import * as Dialog from '$lib/components/ui/dialog';
	import { Input } from '$lib/components/ui/input';
	import { Label } from '$lib/components/ui/label';

	interface Props {
		open: boolean;
		/** Called with false whenever the dialog closes without confirming. */
		onOpenChange: (open: boolean) => void;
		title: string;
		/** What the action destroys. */
		description: Snippet;
		/** The confirm button's label, and its label while the action runs ("Deleting…"). */
		action: string;
		busyAction: string;
		busy: boolean;
		error?: string;
		/** Called with the typed username, only once it matches: the endpoint checks the same
		 *  string, so the dialog hands it over rather than a bare yes. */
		onConfirm: (confirm: string) => void;
		/** What goes between the description and the field: a warning, an option. */
		children?: Snippet;
	}

	let { open, onOpenChange, title, description, action, busyAction, busy, error = '', onConfirm, children }: Props = $props();

	const getUsername = getContext<(() => string | null) | undefined>('username');
	let username = $derived(getUsername?.() ?? '');
	let typed = $state('');
	// An empty username would match an empty field, so a match needs one at all.
	let matches = $derived(!!username && typed === username);
	const id = $props.id();

	// The dialog stays mounted while closed, so a typed name would carry into the next opening.
	$effect.pre(() => {
		if (open) typed = '';
	});

	function confirm() {
		if (matches && !busy) onConfirm(typed);
	}
</script>

<Dialog.Root {open} {onOpenChange}>
	<Dialog.Content class="sm:max-w-md">
		<Dialog.Header>
			<Dialog.Title class="text-destructive">{title}</Dialog.Title>
			<Dialog.Description>{@render description()}</Dialog.Description>
		</Dialog.Header>
		{@render children?.()}
		<div class="min-w-0 space-y-1.5">
			<!-- One span: Label is a flex row, and bare text around the <strong> would be three
			     flex items, wrapping side by side as columns on a phone. -->
			<Label for={id} class="text-sm">
				<span>Type your admin username (<strong>{username}</strong>) to confirm.</span>
			</Label>
			<Input
				{id}
				bind:value={typed}
				placeholder={username}
				disabled={!username || busy}
				onkeydown={(e) => e.key === 'Enter' && confirm()}
			/>
		</div>
		{#if !username}
			<p class="text-sm text-destructive">Your username is unavailable. Reload the page to confirm.</p>
		{:else if error}
			<p class="text-sm text-destructive">{error}</p>
		{/if}
		<Dialog.Footer>
			<Button variant="secondary" onclick={() => onOpenChange(false)} disabled={busy}>Cancel</Button>
			<Button variant="destructive" onclick={confirm} disabled={busy || !matches}>{busy ? busyAction : action}</Button>
		</Dialog.Footer>
	</Dialog.Content>
</Dialog.Root>
