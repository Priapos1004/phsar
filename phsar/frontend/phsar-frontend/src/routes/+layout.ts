import type { LayoutLoad } from './$types';
import { browser } from '$app/environment';
import { redirect } from '@sveltejs/kit';
import { API_URL } from '$lib/config';

export const load: LayoutLoad = async ({ url, fetch }) => {
  if (browser) {
    const token = localStorage.getItem('token');

    // Allow the login page to be public
    if (url.pathname === '/login') {
      return;
    }

    // No token? Redirect to login
    if (!token) {
      throw redirect(302, '/login');
    }

    try {
      const response = await fetch(`${API_URL}/auth/validate`, {
        headers: {
          Authorization: `Bearer ${token}`
        }
      });

      if (response.status === 401) {
        localStorage.removeItem('token');
        throw redirect(302, '/login');
      }

      if (!response.ok) {
        console.error('Unexpected error during token validation:', await response.text());
      }

      // Token valid, continue loading
    } catch (err) {
      console.error('Failed to validate token:', err);
      throw redirect(302, '/login');
    }
  }
};
