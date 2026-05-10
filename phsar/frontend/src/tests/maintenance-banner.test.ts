import { describe, it, expect, vi, beforeEach, afterEach } from 'vitest';
import { render, screen } from '@testing-library/svelte';
import MaintenanceBanner from '../lib/components/MaintenanceBanner.svelte';

describe('MaintenanceBanner', () => {
	const originalFetch = globalThis.fetch;

	beforeEach(() => {
		vi.useFakeTimers();
	});

	afterEach(() => {
		globalThis.fetch = originalFetch;
		vi.useRealTimers();
	});

	function mockStatus(active: boolean, scheduledAt: string | null) {
		globalThis.fetch = vi.fn().mockResolvedValue({
			ok: true,
			status: 200,
			json: () => Promise.resolve({ active, scheduled_at: scheduledAt }),
		});
	}

	it('renders nothing when there is no scheduled or active window', async () => {
		mockStatus(false, null);
		const { container } = render(MaintenanceBanner);
		await vi.waitFor(() => {
			expect(globalThis.fetch).toHaveBeenCalled();
		});
		expect(container.querySelector('[role="status"]')).toBeNull();
	});

	it('shows a countdown when a maintenance window is scheduled within 30 min', async () => {
		const inFifteenMinutes = new Date(Date.now() + 15 * 60_000).toISOString();
		mockStatus(false, inFifteenMinutes);

		render(MaintenanceBanner);
		await vi.waitFor(() => {
			expect(screen.getByRole('status')).toBeInTheDocument();
		});
		// Allow ±1 min slop for fake-timer / Math.round boundary.
		expect(screen.getByRole('status')).toHaveTextContent(/starts in ~(14|15|16) minutes/);
	});

	it('hides the countdown when the schedule is more than 30 min out', async () => {
		const inAnHour = new Date(Date.now() + 60 * 60_000).toISOString();
		mockStatus(false, inAnHour);

		const { container } = render(MaintenanceBanner);
		await vi.waitFor(() => {
			expect(globalThis.fetch).toHaveBeenCalled();
		});
		expect(container.querySelector('[role="status"]')).toBeNull();
	});

	it('shows the in-progress message when active flag is set', async () => {
		mockStatus(true, null);

		render(MaintenanceBanner);
		await vi.waitFor(() => {
			expect(screen.getByRole('status')).toBeInTheDocument();
		});
		expect(screen.getByRole('status')).toHaveTextContent(/Maintenance in progress/);
	});

	it('uses singular "minute" for the 1-minute case', async () => {
		const inOneMinute = new Date(Date.now() + 60_000).toISOString();
		mockStatus(false, inOneMinute);

		render(MaintenanceBanner);
		await vi.waitFor(() => {
			expect(screen.getByRole('status')).toBeInTheDocument();
		});
		expect(screen.getByRole('status')).toHaveTextContent(/starts in ~1 minute(?!s)/);
	});
});
