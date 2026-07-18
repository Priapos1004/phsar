import { get, writable } from 'svelte/store';
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

  // Cross-tab sync. The sliding session silently refreshes the token in the
  // active tab; without this a background tab would keep its now-stale in-memory
  // token, hit the idle deadline against an old `exp`, and log the user out —
  // clearing the shared localStorage and killing every tab. The `storage` event
  // only fires in OTHER tabs (never the one that wrote), so there's no loop;
  // the equality guard avoids a redundant set() (and its clearBellSession).
  window.addEventListener('storage', (e) => {
    if (e.key !== 'token') return;
    if (e.newValue !== get(token)) token.set(e.newValue); // newValue is null on logout
  });
}
