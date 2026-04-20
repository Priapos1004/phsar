import { env } from '$env/dynamic/public';

// Runtime env so svelte-kit sync works without the var set locally.
// Mirrors VersionFooter's approach. In prod, PUBLIC_API_BASE_URL is set
// on the container; in local dev, the fallback points at the dev backend.
export const API_URL = env.PUBLIC_API_BASE_URL || 'http://localhost:8000';
