import { describe, it, expect, vi } from 'vitest';
import { render, screen, fireEvent } from '@testing-library/svelte';
import NavBar from '$lib/components/NavBar.svelte';
import { page } from '$app/state';

describe('NavBar', () => {
	it('renders logo and brand text', () => {
		render(NavBar, { props: { isAuthenticated: false, username: null, isAdmin: false, onLogout: vi.fn() } });
		expect(screen.getByText('PHSAR')).toBeInTheDocument();
	});

	it('renders Ratings and Watchlist links', () => {
		render(NavBar, { props: { isAuthenticated: false, username: null, isAdmin: false, onLogout: vi.fn() } });
		expect(screen.getByText('Ratings')).toBeInTheDocument();
		expect(screen.getByText('Watchlist')).toBeInTheDocument();
	});

	it('hides user dropdown when not authenticated', () => {
		render(NavBar, { props: { isAuthenticated: false, username: null, isAdmin: false, onLogout: vi.fn() } });
		expect(screen.queryByText('T')).not.toBeInTheDocument();
	});

	it('shows user button when authenticated', () => {
		render(NavBar, { props: { isAuthenticated: true, username: 'testuser', isAdmin: false, onLogout: vi.fn() } });
		expect(screen.getByText('T')).toBeInTheDocument();
	});

	it('toggles dropdown on user button click', async () => {
		render(NavBar, { props: { isAuthenticated: true, username: 'testuser', isAdmin: false, onLogout: vi.fn() } });

		// Dropdown not visible initially
		expect(screen.queryByText('User Settings')).not.toBeInTheDocument();

		// Click user button to open dropdown
		await fireEvent.click(screen.getByText('T'));
		expect(screen.getByText('User Settings')).toBeInTheDocument();
		expect(screen.getByText('Add to Library')).toBeInTheDocument();
		expect(screen.getByText('Getting Started')).toBeInTheDocument();
		expect(screen.getByText('Logout')).toBeInTheDocument();

		// Click again to close
		await fireEvent.click(screen.getByText('T'));
		expect(screen.queryByText('User Settings')).not.toBeInTheDocument();
	});

	it('shows Add to Library for guest users (the page itself disables the form)', async () => {
		// All authenticated users get the link — guests can still browse
		// /library/add for the recent additions list. The form on that page
		// is disabled separately based on userRole context.
		render(NavBar, {
			props: {
				isAuthenticated: true,
				username: 'guest',
				isAdmin: false,
				onLogout: vi.fn(),
			},
		});
		await fireEvent.click(screen.getByText('G'));
		expect(screen.getByText('Add to Library')).toBeInTheDocument();
	});

	it('calls onLogout when logout is clicked', async () => {
		const onLogout = vi.fn();
		render(NavBar, { props: { isAuthenticated: true, username: 'testuser', isAdmin: false, onLogout } });

		await fireEvent.click(screen.getByText('T'));
		await fireEvent.click(screen.getByText('Logout'));

		expect(onLogout).toHaveBeenCalledOnce();
	});

	it('has correct link targets', () => {
		render(NavBar, { props: { isAuthenticated: true, username: 'testuser', isAdmin: false, onLogout: vi.fn() } });

		const ratingsLink = screen.getByText('Ratings').closest('a');
		const watchlistLink = screen.getByText('Watchlist').closest('a');
		const homeLink = screen.getByText('PHSAR').closest('a');

		expect(homeLink).toHaveAttribute('href', '/');
		expect(ratingsLink).toHaveAttribute('href', '/ratings');
		expect(watchlistLink).toHaveAttribute('href', '/watchlist');
	});

	it('marks the section the page is in, its sub-routes included, and no other', () => {
		// The mock is a plain object; the cast drops SvelteKit's typed-route pathname.
		const mocked = page as { url: URL };
		const home = mocked.url;
		mocked.url = new URL('http://localhost:5173/browse/fresh');
		try {
			render(NavBar, { props: { isAuthenticated: true, username: 'testuser', isAdmin: false, onLogout: vi.fn() } });
			expect(screen.getByText('Browse').closest('a')).toHaveAttribute('aria-current', 'page');
			expect(screen.getByText('Ratings').closest('a')).not.toHaveAttribute('aria-current');
		} finally {
			mocked.url = home;
		}
	});

	it('marks nothing on a page outside the sections', () => {
		render(NavBar, { props: { isAuthenticated: true, username: 'testuser', isAdmin: false, onLogout: vi.fn() } });
		for (const label of ['Browse', 'Ratings', 'Watchlist']) {
			expect(screen.getByText(label).closest('a')).not.toHaveAttribute('aria-current');
		}
	});
});
