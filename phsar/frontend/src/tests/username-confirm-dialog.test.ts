/**
 * The type-to-confirm dialog every irreversible admin action shares: tested here once rather
 * than through each caller.
 */
import { describe, it, expect, vi } from 'vitest';
import { render, screen, fireEvent } from '@testing-library/svelte';
import { createRawSnippet } from 'svelte';
import UsernameConfirmDialog from '$lib/components/UsernameConfirmDialog.svelte';

const description = createRawSnippet(() => ({ render: () => '<span>Everything goes.</span>' }));

function renderDialog(username: string | null, props: Record<string, unknown> = {}) {
	const onConfirm = vi.fn();
	const view = render(UsernameConfirmDialog, {
		props: { open: true, onOpenChange: vi.fn(), title: 'Wipe it', description, action: 'Wipe', busyAction: 'Wiping…', busy: false, onConfirm, ...props },
		context: new Map([['username', () => username]])
	});
	const button = screen.getByRole('button', { name: props.busy ? 'Wiping…' : 'Wipe' });
	return { onConfirm, view, field: screen.getByLabelText(/type your admin username/i) as HTMLInputElement, button };
}

describe('UsernameConfirmDialog', () => {
	it('confirms only once the typed name matches, handing it over', async () => {
		const { onConfirm, field, button } = renderDialog('admin');
		await fireEvent.input(field, { target: { value: 'admi' } });
		expect(button).toBeDisabled();
		await fireEvent.keyDown(field, { key: 'Enter' });
		expect(onConfirm).not.toHaveBeenCalled();

		await fireEvent.input(field, { target: { value: 'admin' } });
		expect(button).toBeEnabled();
		await fireEvent.keyDown(field, { key: 'Enter' });
		expect(onConfirm).toHaveBeenCalledWith('admin');
	});

	it('never confirms while busy', async () => {
		const { onConfirm, field, button } = renderDialog('admin', { busy: true });
		await fireEvent.input(field, { target: { value: 'admin' } });
		await fireEvent.keyDown(field, { key: 'Enter' });
		expect(button).toBeDisabled();
		expect(onConfirm).not.toHaveBeenCalled();
	});

	it('without a username, says so and never confirms an empty field', async () => {
		const { onConfirm, field, button } = renderDialog(null);
		expect(field).toBeDisabled();
		expect(button).toBeDisabled();
		expect(screen.getByText(/username is unavailable/i)).toBeInTheDocument();
		await fireEvent.keyDown(field, { key: 'Enter' });
		expect(onConfirm).not.toHaveBeenCalled();
	});

	it('opens again with an empty field', async () => {
		const { view, field } = renderDialog('admin');
		await fireEvent.input(field, { target: { value: 'admin' } });
		await view.rerender({ open: false });
		await view.rerender({ open: true });
		expect((screen.getByLabelText(/type your admin username/i) as HTMLInputElement).value).toBe('');
	});
});
