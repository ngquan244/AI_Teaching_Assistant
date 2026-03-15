/**
 * Panel Config Context
 * Fetches panel visibility config from the backend and provides it to the app.
 * Hidden panels are completely removed from the teacher UI.
 */
import React, { createContext, useContext, useState, useEffect, useCallback, useRef, type ReactNode } from 'react';
import { getPanelConfig } from '../api/admin';
import { useAuth } from './AuthContext';

/** How often (ms) to poll for config changes — 30 seconds */
const POLL_INTERVAL = 30_000;
import { TABS, type TabType } from '../types';

// =============================================================================
// Types
// =============================================================================

interface PanelConfigState {
  /** Map of panel key → enabled/disabled */
  panels: Record<string, boolean>;
  /** Whether config has been loaded */
  loaded: boolean;
}

interface PanelConfigContextType extends PanelConfigState {
  /** Check if a specific panel is visible */
  isPanelVisible: (panelKey: string) => boolean;
  /** Get list of visible panel keys */
  visiblePanels: string[];
  /** Refresh config from server */
  refreshPanelConfig: () => Promise<void>;
}

// =============================================================================
// Context
// =============================================================================

const PanelConfigContext = createContext<PanelConfigContextType | undefined>(undefined);

// =============================================================================
// Provider
// =============================================================================

export const PanelConfigProvider: React.FC<{ children: ReactNode }> = ({ children }) => {
  const { isAuthenticated } = useAuth();
  const [state, setState] = useState<PanelConfigState>({
    panels: {},
    loaded: false,
  });

  const fetchConfig = useCallback(async () => {
    try {
      const config = await getPanelConfig();
      setState({
        panels: config.panels,
        loaded: true,
      });
    } catch {
      // If fetch fails, assume all panels are visible
      setState({
        panels: {},
        loaded: true,
      });
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
      // Skip when tab is hidden to save bandwidth
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

  const isPanelVisible = useCallback(
    (panelKey: string): boolean => {
      // If config not loaded yet or panel not in config, default to visible
      if (!state.loaded || !(panelKey in state.panels)) {
        return true;
      }
      return state.panels[panelKey];
    },
    [state],
  );

  const visiblePanels = Object.entries(state.panels)
    .filter(([, enabled]) => enabled)
    .map(([key]) => key);

  const refreshPanelConfig = fetchConfig;

  return (
    <PanelConfigContext.Provider
      value={{
        ...state,
        isPanelVisible,
        visiblePanels,
        refreshPanelConfig,
      }}
    >
      {children}
    </PanelConfigContext.Provider>
  );
};

// =============================================================================
// Hook
// =============================================================================

export const usePanelConfig = (): PanelConfigContextType => {
  const context = useContext(PanelConfigContext);
  if (context === undefined) {
    throw new Error('usePanelConfig must be used within a PanelConfigProvider');
  }
  return context;
};

/**
 * Utility: given activeTab, check if it's disabled and return the first
 * visible tab instead. Returns null if the current tab is fine.
 */
export function getFirstVisibleTab(
  activeTab: TabType,
  isPanelVisible: (key: string) => boolean,
  allTabs: string[],
): TabType | null {
  if (isPanelVisible(activeTab)) return null; // current tab is fine
  const first = allTabs.find((t) => isPanelVisible(t));
  return (first ?? TABS.GUIDE) as TabType;
}

export default PanelConfigContext;
