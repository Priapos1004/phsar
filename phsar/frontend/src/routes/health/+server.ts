/**
 * Liveness probe for the container platform.
 *
 * Deliberately does not touch the backend. A liveness check should only report
 * what restarting *this* container can fix — folding the API's health in would
 * have the frontend restart-loop over an outage no restart of it can repair,
 * while it is still serving pages correctly.
 */
import { json } from '@sveltejs/kit';
import { env } from '$env/dynamic/public';

export const GET = () =>
	json({ status: 'ok', version: env.PUBLIC_APP_VERSION || 'dev' });
