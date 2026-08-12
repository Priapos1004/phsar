/**
 * Liveness probe for the container platform.
 *
 * Deliberately does not touch the backend. A liveness check should only report
 * what restarting *this* container can fix — folding the API's health in would
 * have the frontend restart-loop over an outage it cannot do anything about,
 * and take down the one process still able to serve the maintenance page.
 */
import { json } from '@sveltejs/kit';
import { env } from '$env/dynamic/public';

export const GET = () =>
	json({ status: 'ok', version: env.PUBLIC_APP_VERSION || 'dev' });
