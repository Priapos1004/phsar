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
		try {
			const body = await res.json();
			detail = body.detail || detail;
		} catch {
			// response body wasn't JSON
		}
		throw new ApiError(res.status, detail);
	}
	if (res.status === 204) {
		return undefined as T;
	}
	return res.json();
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
};

export { ApiError };
