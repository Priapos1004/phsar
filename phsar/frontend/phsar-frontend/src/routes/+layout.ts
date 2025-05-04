import type { LayoutLoad } from './$types';
import { browser } from '$app/environment';
import { redirect } from '@sveltejs/kit';

export const load: LayoutLoad = ({ url }) => {
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
  }
};
