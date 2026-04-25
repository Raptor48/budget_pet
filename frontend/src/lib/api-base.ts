/**
 * Normalized backend origin for browser fetch calls.
 * Railway and docs often use a trailing slash in NEXT_PUBLIC_API_URL; paths
 * in this repo always start with `/api/...`, so we strip trailing slashes to
 * avoid `https://host.app//api/...` (404 / broken CORS preflight).
 */
export function getApiBaseUrl(): string {
  return (process.env.NEXT_PUBLIC_API_URL || '').replace(/\/+$/, '');
}
