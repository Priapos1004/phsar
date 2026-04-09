import { describe, it, expect, vi, beforeEach, afterEach } from 'vitest';
import { render, screen, fireEvent } from '@testing-library/svelte';
import LoginPage from '../routes/login/+page.svelte';

// Mock the auth store
vi.mock('$lib/stores/auth', async () => {
	const { writable } = await import('svelte/store');
	return { token: writable(null) };
});

describe('Login page', () => {
	const originalFetch = globalThis.fetch;

	beforeEach(() => {
		vi.restoreAllMocks();
	});

	afterEach(() => {
		globalThis.fetch = originalFetch;
	});

	it('renders login form with username, password, and submit button', () => {
		render(LoginPage);

		expect(screen.getByLabelText('Username')).toBeInTheDocument();
		expect(screen.getByLabelText('Password')).toBeInTheDocument();
		expect(screen.getByRole('button', { name: 'Login' })).toBeInTheDocument();
	});

	it('renders heading', () => {
		render(LoginPage);
		expect(screen.getByRole('heading', { name: 'Login' })).toBeInTheDocument();
	});

	it('username input accepts text', async () => {
		render(LoginPage);
		const input = screen.getByLabelText('Username') as HTMLInputElement;
		await fireEvent.input(input, { target: { value: 'testuser' } });
		expect(input.value).toBe('testuser');
	});

	it('password input is type password', () => {
		render(LoginPage);
		const input = screen.getByLabelText('Password') as HTMLInputElement;
		expect(input.type).toBe('password');
	});

	it('shows error message on failed login', async () => {
		globalThis.fetch = vi.fn().mockResolvedValueOnce({
			ok: false,
			json: () => Promise.resolve({ detail: 'Invalid credentials' }),
		});

		render(LoginPage);
		const usernameInput = screen.getByLabelText('Username');
		const passwordInput = screen.getByLabelText('Password');
		const submitBtn = screen.getByRole('button', { name: 'Login' });

		await fireEvent.input(usernameInput, { target: { value: 'wrong' } });
		await fireEvent.input(passwordInput, { target: { value: 'wrong' } });
		await fireEvent.click(submitBtn);

		// Wait for async login to complete
		await vi.waitFor(() => {
			expect(screen.getByText('Invalid credentials')).toBeInTheDocument();
		});
	});

	it('shows generic error on network failure', async () => {
		globalThis.fetch = vi.fn().mockRejectedValueOnce(new Error('Network error'));

		render(LoginPage);
		await fireEvent.input(screen.getByLabelText('Username'), { target: { value: 'user' } });
		await fireEvent.input(screen.getByLabelText('Password'), { target: { value: 'pass' } });
		await fireEvent.click(screen.getByRole('button', { name: 'Login' }));

		await vi.waitFor(() => {
			expect(screen.getByText('An unexpected error occurred.')).toBeInTheDocument();
		});
	});

	it('calls fetch with correct URL and body on submit', async () => {
		globalThis.fetch = vi.fn().mockResolvedValueOnce({
			ok: true,
			json: () => Promise.resolve({ access_token: 'jwt-token' }),
		});

		render(LoginPage);
		await fireEvent.input(screen.getByLabelText('Username'), { target: { value: 'admin' } });
		await fireEvent.input(screen.getByLabelText('Password'), { target: { value: 'secret' } });
		await fireEvent.click(screen.getByRole('button', { name: 'Login' }));

		await vi.waitFor(() => {
			expect(globalThis.fetch).toHaveBeenCalledWith(
				'http://localhost:8000/auth/login',
				expect.objectContaining({
					method: 'POST',
					headers: { 'Content-Type': 'application/x-www-form-urlencoded' },
				})
			);
		});
	});
});
