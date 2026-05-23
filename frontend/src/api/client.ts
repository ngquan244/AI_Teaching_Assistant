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

/** Prevents multiple concurrent refresh requests */
let isRefreshing = false;
/** Queue of requests waiting for the token refresh to complete */
let failedQueue: Array<{
  resolve: (token: string) => void;
  reject: (error: unknown) => void;
}> = [];

/**
 * Process all queued requests after refresh completes or fails
 */
function processQueue(error: unknown, token: string | null = null): void {
  failedQueue.forEach(({ resolve, reject }) => {
    if (error) {
      reject(error);
    } else {
      resolve(token!);
    }
  });
  failedQueue = [];
}

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
  } catch {
    // Refresh failed — tokens are invalid, force re-login
    removeAllTokens();
    return null;
  }
}

// =============================================================================
// Interceptors
// =============================================================================

// Request interceptor — attach Bearer token
apiClient.interceptors.request.use(
  (config) => {
    const token = getStoredToken();
    if (token) {
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

    // If a refresh is already in progress, queue this request
    if (isRefreshing) {
      return new Promise<string>((resolve, reject) => {
        failedQueue.push({ resolve, reject });
      }).then((token) => {
        originalRequest.headers.Authorization = `Bearer ${token}`;
        return apiClient(originalRequest);
      });
    }

    originalRequest._retry = true;
    isRefreshing = true;

    try {
      const newToken = await refreshAccessToken();

      if (newToken) {
        // Refresh succeeded — replay the original request and queued requests
        processQueue(null, newToken);
        originalRequest.headers.Authorization = `Bearer ${newToken}`;
        return apiClient(originalRequest);
      }

      // Refresh failed — notify the app so it can show a friendly toast / banner
      // BEFORE redirecting, instead of yanking the user to /login mid-action.
      processQueue(error);
      window.dispatchEvent(new CustomEvent(SESSION_EXPIRED_EVENT));
      return Promise.reject(error);
    } catch (refreshError) {
      processQueue(refreshError);
      window.dispatchEvent(new CustomEvent(SESSION_EXPIRED_EVENT));
      return Promise.reject(refreshError);
    } finally {
      isRefreshing = false;
    }
  }
);

export default apiClient;
