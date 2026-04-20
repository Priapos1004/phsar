import { json } from '@sveltejs/kit';
import { env } from '$env/dynamic/public';

export const GET = () =>
	json({ status: 'ok', version: env.PUBLIC_APP_VERSION || 'dev' });
