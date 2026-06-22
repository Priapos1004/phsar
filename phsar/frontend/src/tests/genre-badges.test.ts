import { describe, it, expect, vi, beforeEach } from 'vitest';
import { render, screen } from '@testing-library/svelte';
import GenreBadges from '$lib/components/GenreBadges.svelte';
import { api } from '$lib/api';

vi.mock('$lib/api', () => ({ api: { get: vi.fn() } }));

describe('GenreBadges', () => {
	beforeEach(() => vi.mocked(api.get).mockResolvedValue([]));

	it('renders a badge per genre', () => {
		render(GenreBadges, { props: { genres: ['Action', 'Comedy'] } });
		expect(screen.getByText('Action')).toBeInTheDocument();
		expect(screen.getByText('Comedy')).toBeInTheDocument();
	});

	it('renders nothing when there are no genres', () => {
		const { container } = render(GenreBadges, { props: { genres: [] } });
		expect(container.querySelector('div')).toBeNull();
	});
});
