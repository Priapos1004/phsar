import type { LayoutLoad } from './$types';
import { browser } from '$app/environment';
import { redirect } from '@sveltejs/kit';
import { get } from 'svelte/store';
import { token } from '$lib/stores/auth';
import { api, ApiError } from '$lib/api';

export const load: LayoutLoad = async ({ url }) => {
  if (browser) {
    if (url.pathname === '/login' || url.pathname === '/register') {
      return;
    }

    if (!get(token)) {
      throw redirect(302, '/login');
    }

    try {
      await api.get('/auth/validate');
    } catch (err) {
      if (err instanceof ApiError && err.status === 401) {
        token.set(null);
      }
      throw redirect(302, '/login');
    }
  }
};
