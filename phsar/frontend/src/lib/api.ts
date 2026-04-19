import { API_URL } from '$lib/config';
import { get } from 'svelte/store';
import { token } from '$lib/stores/auth';

class ApiError extends Error {
	status: number;
	detail: string;

	constructor(status: number, detail: string) {
		super(detail);
		this.name = 'ApiError';
		this.status = status;
		this.detail = detail;
		Object.setPrototypeOf(this, ApiError.prototype);
	}
}

function getAuthHeaders(): Record<string, string> {
	const t = get(token);
	if (!t) return {};
	return { Authorization: `Bearer ${t}` };
}

async function handleResponse<T>(res: Response): Promise<T> {
	if (!res.ok) {
		let detail = `Request failed with status ${res.status}`;
		let maintenance = false;
		try {
			const body = await res.json();
			if (typeof body.detail === 'string') {
				detail = body.detail;
			} else if (Array.isArray(body.detail) && body.detail.length > 0) {
				// Pydantic 422 validation errors: [{msg, loc, type}, ...] — show first only
				detail = body.detail[0].msg;
			}
			if (body.maintenance === true) {
				maintenance = true;
			}
		} catch {
			// response body wasn't JSON
		}
		if (maintenance) {
			// Backend is gated during a backup restore. Kick the user to /login
			// so no stale data is visible, and the login page shows the banner.
			token.set(null);
			if (typeof window !== 'undefined' && !window.location.pathname.startsWith('/login')) {
				window.location.href = '/login?maintenance=1';
			}
		}
		throw new ApiError(res.status, detail);
	}
	if (res.status === 204) {
		return undefined as T;
	}
	return res.json();
}

export function parseContentDispositionFilename(header: string | null): string | undefined {
	if (!header) return undefined;
	// RFC 5987 form (filename*=UTF-8''percent-encoded) wins over plain filename when both are present
	const star = /filename\*=\s*(?:UTF-8'')?"?([^";]+)"?/i.exec(header);
	if (star) {
		try {
			return decodeURIComponent(star[1].trim());
		} catch {
			/* fall through */
		}
	}
	const plain = /filename="?([^";]+)"?/i.exec(header);
	return plain?.[1].trim();
}

async function jsonRequest<T>(method: string, path: string, body?: unknown): Promise<T> {
	const res = await fetch(`${API_URL}${path}`, {
		method,
		headers: {
			'Content-Type': 'application/json',
			...getAuthHeaders(),
		},
		body: body ? JSON.stringify(body) : undefined,
	});
	return handleResponse<T>(res);
}

export const api = {
	async get<T = unknown>(path: string, options?: { params?: URLSearchParams }): Promise<T> {
		const url = options?.params ? `${API_URL}${path}?${options.params}` : `${API_URL}${path}`;
		const res = await fetch(url, {
			headers: getAuthHeaders(),
		});
		return handleResponse<T>(res);
	},

	async post<T = unknown>(path: string, body?: unknown): Promise<T> {
		return jsonRequest<T>('POST', path, body);
	},

	async postForm<T = unknown>(path: string, body: URLSearchParams): Promise<T> {
		const res = await fetch(`${API_URL}${path}`, {
			method: 'POST',
			headers: {
				'Content-Type': 'application/x-www-form-urlencoded',
				...getAuthHeaders(),
			},
			body,
		});
		return handleResponse<T>(res);
	},

	async put<T = unknown>(path: string, body?: unknown): Promise<T> {
		return jsonRequest<T>('PUT', path, body);
	},

	async del<T = void>(path: string, body?: unknown): Promise<T> {
		return jsonRequest<T>('DELETE', path, body);
	},

	async downloadBlob(path: string, filename?: string): Promise<void> {
		const res = await fetch(`${API_URL}${path}`, { headers: getAuthHeaders() });
		if (!res.ok) {
			await handleResponse(res);
			return;
		}
		const blob = await res.blob();
		const objectUrl = URL.createObjectURL(blob);
		const anchor = document.createElement('a');
		anchor.href = objectUrl;
		const resolved = filename ?? parseContentDispositionFilename(res.headers.get('Content-Disposition'));
		if (resolved) anchor.download = resolved;
		document.body.appendChild(anchor);
		anchor.click();
		anchor.remove();
		URL.revokeObjectURL(objectUrl);
	},

	async postMultipart<T = unknown>(path: string, formData: FormData): Promise<T> {
		const res = await fetch(`${API_URL}${path}`, {
			method: 'POST',
			headers: getAuthHeaders(),
			body: formData,
		});
		return handleResponse<T>(res);
	},
};

export { ApiError };
