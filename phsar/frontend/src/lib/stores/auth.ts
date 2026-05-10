import { writable } from 'svelte/store';
import { browser } from '$app/environment';
import { clearBellSession } from './bell-session';

const initialToken = browser ? localStorage.getItem('token') : null;

export const token = writable<string | null>(initialToken);

if (browser) {
  token.subscribe((value) => {
    if (value) {
      localStorage.setItem('token', value);
    } else {
      localStorage.removeItem('token');
      // sessionStorage survives a hard nav inside the same tab, so without
      // this every logout-and-back-in path keeps the previous session's
      // bell timestamp + seen-uuids set.
      clearBellSession();
    }
  });
}
