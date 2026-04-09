import { writable } from 'svelte/store';
import type { UserSettings } from '$lib/types/api';

export const userSettings = writable<UserSettings | null>(null);
