/**
 * Model Config Context
 * Fetches enabled providers/models from backend and provides them to the app.
 * When admin disables a provider or model, it disappears from teacher UI.
 * If only 1 provider/model remains, selection UI is hidden entirely.
 */
import React, { createContext, useContext, useState, useEffect, useCallback, useRef, type ReactNode } from 'react';
import { getModelsConfig } from '../api/admin';
import { useAuth } from './AuthContext';

/** How often (ms) to poll for config changes — 30 seconds */
const POLL_INTERVAL = 30_000;

// =============================================================================
// Types
// =============================================================================

interface ModelConfigState {
  enabledProviders: string[];
  enabledModels: Record<string, string[]>;
  providerLabels: Record<string, string>;
  modelLabels: Record<string, string>;
  loaded: boolean;
}

interface ModelConfigContextType extends ModelConfigState {
  /** Is a specific provider enabled? */
  isProviderEnabled: (provider: string) => boolean;
  /** Is a specific model enabled for a given provider? */
  isModelEnabled: (provider: string, model: string) => boolean;
  /** Should we show the provider toggle? (more than 1 enabled) */
  showProviderSwitch: boolean;
  /** Should we show the model dropdown for a provider? (more than 1 enabled model) */
  showModelSelector: (provider: string) => boolean;
  /** Get enabled models for a provider */
  getEnabledModels: (provider: string) => string[];
  /** Refresh from server */
  refreshModelConfig: () => Promise<void>;
}

// =============================================================================
// Context
// =============================================================================

const ModelConfigContext = createContext<ModelConfigContextType | undefined>(undefined);

// =============================================================================
// Provider
// =============================================================================

export const ModelConfigProvider: React.FC<{ children: ReactNode }> = ({ children }) => {
  const { isAuthenticated } = useAuth();
  const [state, setState] = useState<ModelConfigState>({
    enabledProviders: ['groq'],
    enabledModels: {},
    providerLabels: {},
    modelLabels: {},
    loaded: false,
  });

  const fetchConfig = useCallback(async () => {
    try {
      const data = await getModelsConfig();
      setState({
        enabledProviders: data.enabled_providers,
        enabledModels: data.enabled_models,
        providerLabels: data.provider_labels,
        modelLabels: data.model_labels,
        loaded: true,
      });
    } catch {
      // If fetch fails, assume everything enabled
      setState((prev) => ({ ...prev, loaded: true }));
    }
  }, []);

  // Initial fetch
  useEffect(() => {
    if (isAuthenticated) {
      fetchConfig();
    }
  }, [isAuthenticated, fetchConfig]);

  // Polling: re-fetch every POLL_INTERVAL while tab is visible
  const pollRef = useRef<ReturnType<typeof setInterval> | null>(null);

  useEffect(() => {
    if (!isAuthenticated) return;

    const poll = () => {
      if (!document.hidden) {
        fetchConfig();
      }
    };

    pollRef.current = setInterval(poll, POLL_INTERVAL);
    return () => {
      if (pollRef.current) clearInterval(pollRef.current);
    };
  }, [isAuthenticated, fetchConfig]);

  // Also refetch when user returns to the tab (instant catch-up)
  useEffect(() => {
    if (!isAuthenticated) return;
    const onVisibility = () => {
      if (!document.hidden) fetchConfig();
    };
    document.addEventListener('visibilitychange', onVisibility);
    return () => document.removeEventListener('visibilitychange', onVisibility);
  }, [isAuthenticated, fetchConfig]);

  const isProviderEnabled = useCallback(
    (provider: string) => {
      if (!state.loaded) return true;
      return state.enabledProviders.includes(provider);
    },
    [state],
  );

  const isModelEnabled = useCallback(
    (provider: string, model: string) => {
      if (!state.loaded) return true;
      return state.enabledModels[provider]?.includes(model) ?? true;
    },
    [state],
  );

  const showProviderSwitch = state.enabledProviders.length > 1;

  const showModelSelector = useCallback(
    (provider: string) => {
      const models = state.enabledModels[provider];
      return models ? models.length > 1 : true;
    },
    [state],
  );

  const getEnabledModels = useCallback(
    (provider: string) => {
      return state.enabledModels[provider] ?? [];
    },
    [state],
  );

  return (
    <ModelConfigContext.Provider
      value={{
        ...state,
        isProviderEnabled,
        isModelEnabled,
        showProviderSwitch,
        showModelSelector,
        getEnabledModels,
        refreshModelConfig: fetchConfig,
      }}
    >
      {children}
    </ModelConfigContext.Provider>
  );
};

// =============================================================================
// Hook
// =============================================================================

export const useModelConfig = (): ModelConfigContextType => {
  const context = useContext(ModelConfigContext);
  if (context === undefined) {
    throw new Error('useModelConfig must be used within a ModelConfigProvider');
  }
  return context;
};

export default ModelConfigContext;
