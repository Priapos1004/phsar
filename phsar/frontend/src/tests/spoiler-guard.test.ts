import { describe, it, expect, beforeEach } from 'vitest';
import { render, screen, fireEvent } from '@testing-library/svelte';
import { userSettings } from '$lib/stores/userSettings';
import SpoilerGuardTest from './SpoilerGuardTest.svelte';

// Helper to set spoiler level before render
function setSettings(spoiler_level: 'off' | 'blur' | 'hide') {
	userSettings.set({
		theme: 'default',
		name_language: 'english',
		default_search_view: 'anime',
		rating_step: '0.5',
		spoiler_level,
	});
}

beforeEach(() => {
	userSettings.set(null);
});

describe('SpoilerGuard', () => {
	it('renders children normally when spoiler_level is off', () => {
		setSettings('off');
		render(SpoilerGuardTest, { props: { visible: false, mode: 'image' } });
		expect(screen.getByText('Test Content')).toBeInTheDocument();
		expect(screen.queryByText('Click to reveal')).not.toBeInTheDocument();
	});

	it('renders children normally when visible is true', () => {
		setSettings('blur');
		render(SpoilerGuardTest, { props: { visible: true, mode: 'image' } });
		expect(screen.getByText('Test Content')).toBeInTheDocument();
		expect(screen.queryByText('Click to reveal')).not.toBeInTheDocument();
	});

	it('blurs content and shows reveal overlay when blur mode + not visible', () => {
		setSettings('blur');
		render(SpoilerGuardTest, { props: { visible: false, mode: 'image' } });
		expect(screen.getByText('Test Content')).toBeInTheDocument();
		expect(screen.getByText('Click to reveal')).toBeInTheDocument();
	});

	it('reveals content on click', async () => {
		setSettings('blur');
		render(SpoilerGuardTest, { props: { visible: false, mode: 'image' } });
		expect(screen.getByText('Click to reveal')).toBeInTheDocument();

		await fireEvent.click(screen.getByRole('button'));
		// After click, reveal overlay should be gone
		expect(screen.queryByText('Click to reveal')).not.toBeInTheDocument();
		expect(screen.getByText('Test Content')).toBeInTheDocument();
	});

	it('blurs content in hide mode (detail page fallback)', () => {
		setSettings('hide');
		render(SpoilerGuardTest, { props: { visible: false, mode: 'image' } });
		// Hide mode on detail pages falls back to blur behavior
		expect(screen.getByText('Test Content')).toBeInTheDocument();
		expect(screen.getByText('Click to reveal')).toBeInTheDocument();
	});

	it('renders normally when settings are null', () => {
		userSettings.set(null);
		render(SpoilerGuardTest, { props: { visible: false, mode: 'image' } });
		// null settings → spoiler_level defaults to 'off'
		expect(screen.getByText('Test Content')).toBeInTheDocument();
		expect(screen.queryByText('Click to reveal')).not.toBeInTheDocument();
	});
});
