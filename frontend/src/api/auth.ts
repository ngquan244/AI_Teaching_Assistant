/**
 * Authentication API client
 * Handles signup, login, and profile endpoints
 */
import { apiClient, getStoredRefreshToken } from './client';

// =============================================================================
// Types
// =============================================================================

export interface User {
  id: string;
  email: string;
  name: string;
  role: 'ADMIN' | 'TEACHER';
  status: 'ACTIVE' | 'DISABLED' | 'PENDING';
  created_at: string;
  last_login_at: string | null;
}

export interface AuthTokens {
  access_token: string;
  refresh_token: string;
  token_type: string;
  expires_in: number;
}

export interface LoginRequest {
  email: string;
  password: string;
}

export interface SignupRequest {
  email: string;
  name: string;
  password: string;
  invite_code?: string;
  canvas_access_token?: string;
  canvas_domain?: string;
}

export interface SignupStatusResponse {
  mode: 'open' | 'invite' | 'closed';
}

export interface LoginResponse {
  user: User;
  tokens: AuthTokens;
}

export interface SignupResponse {
  user: User;
  tokens: AuthTokens;
  message: string;
}

export interface CanvasToken {
  id: string;
  canvas_domain: string;
  token_type: 'PAT' | 'OAUTH';
  label: string | null;
  created_at: string;
  last_used_at: string | null;
  is_active: boolean;
}

export interface UserProfileResponse {
  user: User;
  canvas_tokens: CanvasToken[];
}

export interface ApiError {
  success: false;
  error: string;
  error_code: string;
}

// =============================================================================
// API Functions
// =============================================================================

/**
 * Get signup mode (public — no auth required)
 */
export async function getSignupStatus(): Promise<SignupStatusResponse> {
  const response = await apiClient.get<SignupStatusResponse>('/api/auth/signup-status');
  return response.data;
}

/**
 * Register a new user account
 */
export async function signup(data: SignupRequest): Promise<SignupResponse> {
  const response = await apiClient.post<SignupResponse>('/api/auth/signup', data);
  return response.data;
}

/**
 * Login with email and password
 */
export async function login(data: LoginRequest): Promise<LoginResponse> {
  const response = await apiClient.post<LoginResponse>('/api/auth/login', data);
  return response.data;
}

/**
 * Get current user profile
 */
export async function getProfile(): Promise<UserProfileResponse> {
  const response = await apiClient.get<UserProfileResponse>('/api/auth/me');
  return response.data;
}

/**
 * Add a Canvas LMS access token
 */
export async function addCanvasToken(data: {
  canvas_domain: string;
  access_token: string;
  token_type?: 'PAT' | 'OAUTH';
  label?: string;
}): Promise<CanvasToken> {
  const response = await apiClient.post<CanvasToken>('/api/auth/canvas-tokens', data);
  return response.data;
}

/**
 * Revoke a Canvas token
 */
export async function revokeCanvasToken(tokenId: string): Promise<void> {
  await apiClient.delete(`/api/auth/canvas-tokens/${tokenId}`);
}

/**
 * Logout and revoke current session server-side.
 */
export async function logout(logoutAllDevices: boolean = false): Promise<void> {
  try {
    await apiClient.post('/api/auth/logout', {
      refresh_token: getStoredRefreshToken(),
      logout_all_devices: logoutAllDevices,
    });
  } catch {
    // Frontend still clears local state even if revoke request fails.
  }
}

// Export all auth API functions
export const authApi = {
  signup,
  login,
  getProfile,
  addCanvasToken,
  revokeCanvasToken,
  logout,
};

export default authApi;
