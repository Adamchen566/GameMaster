const DEFAULT_API_BASE_URL = "/api";

/**
 * Base URL the browser uses to reach the API.
 *
 * Defaults to `/api`, which the Vite dev server proxies to the backend, so the
 * page and the API share an origin. Set `VITE_API_BASE_URL` to override it.
 */
export function getApiBaseUrl(): string {
  const configured = import.meta.env.VITE_API_BASE_URL?.trim();
  const baseUrl = configured ? configured : DEFAULT_API_BASE_URL;

  return baseUrl.replace(/\/+$/, "");
}
