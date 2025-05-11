import { goto } from '$app/navigation';
import type { SearchParams } from '$lib/utils/search';
import LZString from 'lz-string';
const { compressToEncodedURIComponent } = LZString;

export function buildSearchUrl(params: SearchParams): string {
    const encoded = compressToEncodedURIComponent(JSON.stringify(params));
    return `/search?q=${encoded}`;
}

export function navigateToSearch(params: SearchParams) {
    const search_url = buildSearchUrl(params);
    console.debug(search_url);
    goto(search_url);
}
