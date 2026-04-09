import { describe, it, expect, vi } from 'vitest';
import { render, screen, fireEvent } from '@testing-library/svelte';
import NavBar from '$lib/components/NavBar.svelte';

describe('NavBar', () => {
	it('renders logo and brand text', () => {
		render(NavBar, { props: { isAuthenticated: false, username: null, onLogout: vi.fn() } });
		expect(screen.getByText('PHSAR')).toBeInTheDocument();
	});

	it('renders Ratings and Watchlist links', () => {
		render(NavBar, { props: { isAuthenticated: false, username: null, onLogout: vi.fn() } });
		expect(screen.getByText('Ratings')).toBeInTheDocument();
		expect(screen.getByText('Watchlist')).toBeInTheDocument();
	});

	it('hides user dropdown when not authenticated', () => {
		render(NavBar, { props: { isAuthenticated: false, username: null, onLogout: vi.fn() } });
		expect(screen.queryByText('T')).not.toBeInTheDocument();
	});

	it('shows user button when authenticated', () => {
		render(NavBar, { props: { isAuthenticated: true, username: 'testuser', onLogout: vi.fn() } });
		expect(screen.getByText('T')).toBeInTheDocument();
	});

	it('toggles dropdown on user button click', async () => {
		render(NavBar, { props: { isAuthenticated: true, username: 'testuser', onLogout: vi.fn() } });

		// Dropdown not visible initially
		expect(screen.queryByText('User Settings')).not.toBeInTheDocument();

		// Click user button to open dropdown
		await fireEvent.click(screen.getByText('T'));
		expect(screen.getByText('User Settings')).toBeInTheDocument();
		expect(screen.getByText('Statistics')).toBeInTheDocument();
		expect(screen.getByText('Getting Started')).toBeInTheDocument();
		expect(screen.getByText('Logout')).toBeInTheDocument();

		// Click again to close
		await fireEvent.click(screen.getByText('T'));
		expect(screen.queryByText('User Settings')).not.toBeInTheDocument();
	});

	it('calls onLogout when logout is clicked', async () => {
		const onLogout = vi.fn();
		render(NavBar, { props: { isAuthenticated: true, username: 'testuser', onLogout } });

		await fireEvent.click(screen.getByText('T'));
		await fireEvent.click(screen.getByText('Logout'));

		expect(onLogout).toHaveBeenCalledOnce();
	});

	it('has correct link targets', () => {
		render(NavBar, { props: { isAuthenticated: true, username: 'testuser', onLogout: vi.fn() } });

		const ratingsLink = screen.getByText('Ratings').closest('a');
		const watchlistLink = screen.getByText('Watchlist').closest('a');
		const homeLink = screen.getByText('PHSAR').closest('a');

		expect(homeLink).toHaveAttribute('href', '/');
		expect(ratingsLink).toHaveAttribute('href', '/ratings');
		expect(watchlistLink).toHaveAttribute('href', '/watchlist');
	});
});
