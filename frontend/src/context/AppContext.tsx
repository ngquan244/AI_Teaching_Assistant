import React, { createContext, useContext, useState, useEffect, useCallback, type ReactNode } from 'react';
import { configApi } from '../api/config';
import type { ConfigResponse, ChatMessage, ToolUsage } from '../types';

interface AppContextType {
  config: ConfigResponse | null;
  loading: boolean;
  model: string;
  setModel: (model: string) => void;
  maxIterations: number;
  setMaxIterations: (n: number) => void;
  // Provider switching
  switchingProvider: boolean;
  switchProvider: (provider: string) => Promise<void>;
  // Chat state - persisted across tab switches
  chatMessages: ChatMessage[];
  setChatMessages: React.Dispatch<React.SetStateAction<ChatMessage[]>>;
  chatToolsUsed: ToolUsage[];
  setChatToolsUsed: React.Dispatch<React.SetStateAction<ToolUsage[]>>;
  clearChat: () => void;
}

const AppContext = createContext<AppContextType | undefined>(undefined);

export const AppProvider: React.FC<{ children: ReactNode }> = ({ children }) => {
  const [config, setConfig] = useState<ConfigResponse | null>(null);
  const [loading, setLoading] = useState(true);
  const [model, setModel] = useState('llama-3.3-70b-versatile');
  const [maxIterations, setMaxIterations] = useState(10);
  const [switchingProvider, setSwitchingProvider] = useState(false);
  
  // Chat state - persisted across tab switches
  const [chatMessages, setChatMessages] = useState<ChatMessage[]>([]);
  const [chatToolsUsed, setChatToolsUsed] = useState<ToolUsage[]>([]);

  const clearChat = () => {
    setChatMessages([]);
    setChatToolsUsed([]);
  };

  useEffect(() => {
    loadConfig();
  }, []);

  const loadConfig = async () => {
    try {
      const data = await configApi.getConfig();
      setConfig(data);
      setModel(data.default_model);
      setMaxIterations(data.max_iterations);
    } catch (error) {
      console.error('Failed to load config:', error);
    } finally {
      setLoading(false);
    }
  };

  const switchProvider = useCallback(async (provider: string) => {
    setSwitchingProvider(true);
    try {
      const res = await configApi.switchProvider(provider);
      // Update config with new provider info
      setConfig((prev) =>
        prev
          ? {
              ...prev,
              llm_provider: res.provider,
              available_models: res.available_models,
              default_model: res.default_model,
            }
          : prev
      );
      // Reset model to default for the new provider
      setModel(res.default_model);
    } catch (error) {
      console.error('Failed to switch provider:', error);
      throw error;
    } finally {
      setSwitchingProvider(false);
    }
  }, []);

  return (
    <AppContext.Provider
      value={{
        config,
        loading,
        model,
        setModel,
        maxIterations,
        setMaxIterations,
        switchingProvider,
        switchProvider,
        chatMessages,
        setChatMessages,
        chatToolsUsed,
        setChatToolsUsed,
        clearChat,
      }}
    >
      {children}
    </AppContext.Provider>
  );
};

export const useApp = () => {
  const context = useContext(AppContext);
  if (context === undefined) {
    throw new Error('useApp must be used within an AppProvider');
  }
  return context;
};
