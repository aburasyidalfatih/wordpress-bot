export interface ApiFetchOptions extends RequestInit {
  /**
   * When true (the default), a 401 response clears the stored token and sends the
   * user to /login. Pass false for requests that may legitimately be
   * unauthenticated (public pages, login endpoints): the 401 response is then
   * returned untouched and the stored token is kept.
   */
  redirectOnUnauthorized?: boolean;
  /**
   * When true (the default), the stored token is sent as a Bearer header. Login
   * endpoints pass false so a stale token from an old session is not sent along.
   */
  sendToken?: boolean;
}

const PUBLIC_PATHS = new Set(['/', '/login', '/register']);

export async function apiFetch(
  url: string,
  { redirectOnUnauthorized = true, sendToken = true, ...options }: ApiFetchOptions = {},
) {
  const token = sendToken ? localStorage.getItem('token') : null;
  const headers = new Headers(options.headers || {});

  if (token) {
    headers.set('Authorization', `Bearer ${token}`);
  }

  const response = await fetch(url, { ...options, headers, credentials: 'include' });

  if (response.status === 401 && redirectOnUnauthorized) {
    localStorage.removeItem('token');
    if (!PUBLIC_PATHS.has(window.location.pathname)) {
      window.location.href = '/login';
    }
  }

  return response;
}

/** True for the error thrown by fetch() when its AbortSignal fires. */
export function isAbortError(error: unknown): boolean {
  return error instanceof DOMException && error.name === 'AbortError';
}

/** Message for an unknown thrown value, falling back to `fallback`. */
export function errorMessage(error: unknown, fallback: string): string {
  return error instanceof Error && error.message ? error.message : fallback;
}

export const NETWORK_ERROR = 'Gagal terhubung ke server. Periksa koneksi Anda lalu coba lagi.';

/**
 * GET (by default) a JSON endpoint. Rejects with a readable Error when the
 * response is not 2xx, preferring the backend's `error` field.
 */
export async function fetchJson<T>(url: string, options: ApiFetchOptions = {}, failureMessage = 'Gagal memuat data'): Promise<T> {
  const res = await apiFetch(url, options);
  if (!res.ok) {
    const payload = await res.json().catch(() => ({}));
    throw new Error(payload?.error || `${failureMessage} (HTTP ${res.status}).`);
  }
  return res.json() as Promise<T>;
}
