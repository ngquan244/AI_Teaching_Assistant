import axios, { type AxiosError, type InternalAxiosRequestConfig } from 'axios';

const API_BASE_URL = import.meta.env.VITE_API_URL || '';

// Token storage keys
const TOKEN_KEY = 'grader_access_token';
const REFRESH_TOKEN_KEY = 'grader_refresh_token';

export const apiClient = axios.create({
  baseURL: API_BASE_URL,
  headers: {
    'Content-Type': 'application/json',
  },
});

// =============================================================================
// Token Management
// =============================================================================

/**
 * Get the stored access token
 */
export function getStoredToken(): string | null {
  return localStorage.getItem(TOKEN_KEY);
}

/**
 * Store the access token
 */
export function setStoredToken(token: string): void {
  localStorage.setItem(TOKEN_KEY, token);
  sessionExpiredDispatched = false;
}

/**
 * Remove the stored access token
 */
export function removeStoredToken(): void {
  localStorage.removeItem(TOKEN_KEY);
}

/**
 * Get the stored refresh token
 */
export function getStoredRefreshToken(): string | null {
  return localStorage.getItem(REFRESH_TOKEN_KEY);
}

/**
 * Store the refresh token
 */
export function setStoredRefreshToken(token: string): void {
  localStorage.setItem(REFRESH_TOKEN_KEY, token);
}

/**
 * Remove the stored refresh token
 */
export function removeStoredRefreshToken(): void {
  localStorage.removeItem(REFRESH_TOKEN_KEY);
}

/**
 * Remove all auth tokens (access + refresh)
 */
export function removeAllTokens(): void {
  removeStoredToken();
  removeStoredRefreshToken();
}

// =============================================================================
// Session expiry signal
// =============================================================================

/**
 * Custom event dispatched when the refresh token also fails — i.e. the user's
 * session is genuinely over and they need to re-login. Components listen for
 * this to show a friendly toast / banner before navigation, instead of being
 * yanked to /login mid-action.
 */
export const SESSION_EXPIRED_EVENT = 'auth:session-expired';

let sessionExpiredDispatched = false;

function dispatchSessionExpiredOnce(): void {
  if (sessionExpiredDispatched) return;
  sessionExpiredDispatched = true;
  window.dispatchEvent(new CustomEvent(SESSION_EXPIRED_EVENT));
}

/** Lightweight retry policy for transient network / 5xx errors on safe methods. */
const TRANSIENT_RETRY_DELAY_MS = 800;
const SAFE_METHODS = new Set(['get', 'head', 'options']);

function isTransientNetworkError(error: AxiosError): boolean {
  // No response = network drop, DNS issue, CORS preflight fail, etc.
  if (!error.response) return true;
  const status = error.response.status;
  return status === 502 || status === 503 || status === 504;
}

// =============================================================================
// Token Refresh Logic
// =============================================================================

/** Shared refresh promise so parallel 401s cannot create a refresh storm. */
let refreshPromise: Promise<string | null> | null = null;

/**
 * Attempt to refresh the access token using the refresh token.
 * Returns the new access token or null if refresh failed.
 */
async function refreshAccessToken(): Promise<string | null> {
  const refreshToken = getStoredRefreshToken();
  if (!refreshToken) return null;

  try {
    // Use raw axios (not apiClient) to avoid interceptor loops
    const response = await axios.post(`${API_BASE_URL}/api/auth/refresh`, {
      refresh_token: refreshToken,
    });

    const { access_token, refresh_token: newRefreshToken } = response.data;
    setStoredToken(access_token);
    setStoredRefreshToken(newRefreshToken);
    return access_token;
  } catch (error) {
    const status = (error as AxiosError).response?.status;
    if (status !== 401 && status !== 403) {
      throw error;
    }
    // Refresh failed — tokens are invalid, force re-login
    removeAllTokens();
    return null;
  }
}

function getRefreshPromise(): Promise<string | null> {
  if (!refreshPromise) {
    refreshPromise = refreshAccessToken().finally(() => {
      refreshPromise = null;
    });
  }
  return refreshPromise;
}

function requestPath(url: string | undefined): string {
  if (!url) return '';
  try {
    return new URL(url, API_BASE_URL || window.location.origin).pathname;
  } catch {
    return url;
  }
}

function isCanvasIntegrationPath(url: string | undefined): boolean {
  const path = requestPath(url);
  return (
    path === '/api/canvas' ||
    path.startsWith('/api/canvas/') ||
    path.startsWith('/api/canvas-')
  );
}

function isAuthFlowEndpoint(url: string | undefined): boolean {
  const path = requestPath(url);
  return (
    path === '/api/auth/login' ||
    path === '/api/auth/signup' ||
    path === '/api/auth/signup-status' ||
    path === '/api/auth/logout' ||
    path === '/api/auth/refresh'
  );
}

function isPublicAuthEndpoint(url: string | undefined): boolean {
  const path = requestPath(url);
  return (
    path === '/api/auth/login' ||
    path === '/api/auth/signup' ||
    path === '/api/auth/signup-status' ||
    path === '/api/auth/refresh'
  );
}

function getResponseDetail(error: AxiosError): string {
  const data = error.response?.data as { detail?: unknown; error?: unknown } | undefined;
  const raw = data?.detail ?? data?.error ?? '';
  return typeof raw === 'string' ? raw : JSON.stringify(raw);
}

function isTerminalAuth401(error: AxiosError): boolean {
  const detail = getResponseDetail(error).toLowerCase();
  return (
    detail.includes('token has been revoked') ||
    detail.includes('logged out from all devices') ||
    detail.includes('user not found')
  );
}

function isAppAuth401(error: AxiosError): boolean {
  const authHeader = error.response?.headers?.['www-authenticate'];
  if (typeof authHeader === 'string' && authHeader.toLowerCase().includes('bearer')) {
    return true;
  }

  const detail = getResponseDetail(error).toLowerCase();
  return (
    detail.includes('invalid or expired token') ||
    detail.includes('token has been revoked') ||
    detail.includes('user not found')
  );
}

function shouldSkipRefreshForCanvas401(error: AxiosError): boolean {
  return (
    error.response?.status === 401 &&
    isCanvasIntegrationPath(error.config?.url) &&
    !isAppAuth401(error)
  );
}

// =============================================================================
// Interceptors
// =============================================================================

// Request interceptor — attach Bearer token
apiClient.interceptors.request.use(
  (config) => {
    const token = getStoredToken();
    if (token && !isPublicAuthEndpoint(config.url)) {
      config.headers.Authorization = `Bearer ${token}`;
    }
    return config;
  },
  (error) => {
    return Promise.reject(error);
  }
);

// Response interceptor — auto-refresh on 401, retry once on transient network errors
apiClient.interceptors.response.use(
  (response) => response,
  async (error: AxiosError) => {
    const originalRequest = error.config as
      | (InternalAxiosRequestConfig & { _retry?: boolean; _transientRetry?: boolean })
      | undefined;

    // Only attempt refresh on 401 and if we haven't already retried this request
    const is401 = error.response?.status === 401;
    const alreadyRetried = originalRequest?._retry;
    const isRefreshCall = originalRequest?.url?.includes('/api/auth/refresh');
    const isAuthFlowCall = isAuthFlowEndpoint(originalRequest?.url);

    // -----------------------------------------------------------------
    // Transient network / gateway error → one silent retry for safe methods.
    // This avoids surfacing scary "Network error" toasts to the user when
    // the backend is just briefly unreachable (worker restart, brief 502
    // from the proxy, flaky Wi-Fi, ...).
    // -----------------------------------------------------------------
    if (
      originalRequest &&
      !is401 &&
      !originalRequest._transientRetry &&
      isTransientNetworkError(error) &&
      SAFE_METHODS.has((originalRequest.method || 'get').toLowerCase())
    ) {
      originalRequest._transientRetry = true;
      await new Promise((r) => setTimeout(r, TRANSIENT_RETRY_DELAY_MS));
      return apiClient(originalRequest);
    }

    if (!is401 || alreadyRetried || isRefreshCall || !originalRequest) {
      return Promise.reject(error);
    }

    if (shouldSkipRefreshForCanvas401(error)) {
      return Promise.reject(error);
    }

    if (isAuthFlowCall) {
      return Promise.reject(error);
    }

    if (isTerminalAuth401(error)) {
      removeAllTokens();
      dispatchSessionExpiredOnce();
      return Promise.reject(error);
    }

    originalRequest._retry = true;

    try {
      const newToken = await getRefreshPromise();

      if (newToken) {
        // Refresh succeeded — replay the original request and queued requests
        originalRequest.headers.Authorization = `Bearer ${newToken}`;
        return apiClient(originalRequest);
      }

      // Refresh failed — notify the app so it can show a friendly toast / banner
      // BEFORE redirecting, instead of yanking the user to /login mid-action.
      dispatchSessionExpiredOnce();
      return Promise.reject(error);
    } catch (refreshError) {
      return Promise.reject(refreshError);
    }
  }
);

export default apiClient;
