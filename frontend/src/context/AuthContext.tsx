/**
 * Authentication Context
 * Manages user authentication state and provides auth methods
 */
import React, { createContext, useContext, useState, useEffect, useCallback, type ReactNode } from 'react';
import { authApi, type User, type LoginRequest, type SignupRequest, type CanvasToken } from '../api/auth';
import {
  getStoredToken,
  setStoredToken,
  setStoredRefreshToken,
  removeAllTokens,
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
