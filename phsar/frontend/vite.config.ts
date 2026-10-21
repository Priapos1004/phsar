import { sveltekit } from '@sveltejs/kit/vite';
import { defineConfig } from 'vitest/config';
import tailwindcss from '@tailwindcss/vite'

export default defineConfig(({ mode }) => ({
	plugins: [sveltekit(), tailwindcss()],
	test: {
		include: ['src/**/*.test.ts'],
		environment: 'jsdom',
		setupFiles: ['src/tests/setup.ts'],
		globals: true,
	},
	// The tests need Svelte's browser build under jsdom, and only the tests (Vitest runs in
	// `test` mode): a top-level `conditions` replaces Vite's default client list rather than
	// adding to it, which drops `development|production` — `esm-env` then can't tell the two
	// apart in the browser, and Svelte's dev warnings and `$app/environment`'s `dev` go quiet.
	resolve: mode === 'test' ? { conditions: ['browser'] } : undefined,
}));
