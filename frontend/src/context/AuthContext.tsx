/**
 * Authentication Context
 * Manages user authentication state and provides auth methods
 */
import React, { createContext, useContext, useState, useEffect, useCallback, type ReactNode } from 'react';
import type { AxiosError } from 'axios';
import { authApi, type User, type LoginRequest, type SignupRequest, type CanvasToken } from '../api/auth';
import {
  getStoredToken,
  setStoredToken,
  setStoredRefreshToken,
  removeAllTokens,
  SESSION_EXPIRED_EVENT,
} from '../api/client';

// =============================================================================
// Types
// =============================================================================

interface AuthState {
  user: User | null;
  canvasTokens: CanvasToken[];
  isAuthenticated: boolean;
  isLoading: boolean;
}

interface AuthContextType extends AuthState {
  login: (data: LoginRequest) => Promise<void>;
  signup: (data: SignupRequest) => Promise<void>;
  logout: () => Promise<void>;
  refreshProfile: () => Promise<void>;
}

// =============================================================================
// Context
// =============================================================================

const AuthContext = createContext<AuthContextType | undefined>(undefined);

function getErrorDetail(error: unknown): string {
  const axiosError = error as AxiosError<{ detail?: unknown; error?: unknown }>;
  const raw = axiosError.response?.data?.detail ?? axiosError.response?.data?.error ?? '';
  return typeof raw === 'string' ? raw : JSON.stringify(raw);
}

function isTerminalAuthError(error: unknown): boolean {
  const axiosError = error as AxiosError;
  const status = axiosError.response?.status;
  if (status !== 401 && status !== 403) return false;

  const detail = getErrorDetail(error).toLowerCase();
  return (
    detail.includes('invalid or expired token') ||
    detail.includes('invalid or expired refresh token') ||
    detail.includes('refresh token has been revoked') ||
    detail.includes('token has been revoked') ||
    detail.includes('logged out from all devices') ||
    detail.includes('user not found')
  );
}

// =============================================================================
// Provider
// =============================================================================

export const AuthProvider: React.FC<{ children: ReactNode }> = ({ children }) => {
  const [state, setState] = useState<AuthState>({
    user: null,
    canvasTokens: [],
    isAuthenticated: false,
    isLoading: true, // Start loading to check for existing token
  });

  /**
   * Fetch user profile from API
   */
  const fetchProfile = useCallback(async () => {
    try {
      const profile = await authApi.getProfile();
      setState({
        user: profile.user,
        canvasTokens: profile.canvas_tokens,
        isAuthenticated: true,
        isLoading: false,
      });
    } catch (error) {
      if (!isTerminalAuthError(error)) {
        // Transient profile failures (network, 429, 5xx) should not destroy a
        // still-valid local session. Keep the current auth state and stop loading.
        setState(prev => ({ ...prev, isLoading: false }));
        return;
      }
      // Token invalid or expired — clear all tokens
      removeAllTokens();
      setState({
        user: null,
        canvasTokens: [],
        isAuthenticated: false,
        isLoading: false,
      });
    }
  }, []);

  /**
   * Check for existing token on mount
   */
  useEffect(() => {
    const token = getStoredToken();
    if (token) {
      fetchProfile();
    } else {
      setState(prev => ({ ...prev, isLoading: false }));
    }
  }, [fetchProfile]);

  useEffect(() => {
    const handleSessionExpired = () => {
      removeAllTokens();
      setState({
        user: null,
        canvasTokens: [],
        isAuthenticated: false,
        isLoading: false,
      });
    };

    window.addEventListener(SESSION_EXPIRED_EVENT, handleSessionExpired);
    return () => window.removeEventListener(SESSION_EXPIRED_EVENT, handleSessionExpired);
  }, []);

  /**
   * Login with email and password
   */
  const login = async (data: LoginRequest): Promise<void> => {
    try {
      const response = await authApi.login(data);
      
      // Store both tokens
      setStoredToken(response.tokens.access_token);
      setStoredRefreshToken(response.tokens.refresh_token);
      
      // Fetch full profile (includes canvas tokens)
      await fetchProfile();
    } catch (error) {
      throw error;
    }
  };

  /**
   * Register new user and auto-login
   */
  const signup = async (data: SignupRequest): Promise<void> => {
    try {
      const response = await authApi.signup(data);
      
      // Store both tokens
      setStoredToken(response.tokens.access_token);
      setStoredRefreshToken(response.tokens.refresh_token);
      
      // Fetch full profile
      await fetchProfile();
    } catch (error) {
      throw error;
    }
  };

  /**
   * Logout and clear state
   */
  const logout = async (): Promise<void> => {
    try {
      await authApi.logout();
    } finally {
      removeAllTokens();
      setState({
        user: null,
        canvasTokens: [],
        isAuthenticated: false,
        isLoading: false,
      });
    }
  };

  /**
   * Refresh user profile
   */
  const refreshProfile = async (): Promise<void> => {
    if (getStoredToken()) {
      await fetchProfile();
    }
  };

  return (
    <AuthContext.Provider
      value={{
        ...state,
        login,
        signup,
        logout,
        refreshProfile,
      }}
    >
      {children}
    </AuthContext.Provider>
  );
};

// =============================================================================
// Hook
// =============================================================================

export const useAuth = (): AuthContextType => {
  const context = useContext(AuthContext);
  if (context === undefined) {
    throw new Error('useAuth must be used within an AuthProvider');
  }
  return context;
};

export default AuthContext;
