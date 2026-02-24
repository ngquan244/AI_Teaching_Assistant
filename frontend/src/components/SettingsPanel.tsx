import React, { useState, useEffect } from 'react';
import { useApp } from '../context/AppContext';
import { useAuth } from '../context/AuthContext';
import { useModelConfig } from '../context/ModelConfigContext';
import { authApi } from '../api/auth';
import { clearCanvasTokenCache } from '../api/canvas';
import { clearCanvasRagTokenCache } from '../api/canvasRag';
import {
  Settings,
  Cpu,
  Key,
  Eye,
  EyeOff,
  CheckCircle,
  AlertTriangle,
  ExternalLink,
  Loader2,
  Edit2,
  X,
} from 'lucide-react';

const DEFAULT_CANVAS_URL = 'https://lms.uet.vnu.edu.vn';

const SettingsPanel: React.FC = () => {
  const { config, model, setModel, maxIterations, setMaxIterations } = useApp();
  const { showModelSelector, getEnabledModels } = useModelConfig();
  const { canvasTokens, refreshProfile, isAuthenticated } = useAuth();

  // Canvas settings state
  const [isEditMode, setIsEditMode] = useState(false);
  const [canvasToken, setCanvasToken] = useState('');
  const [canvasUrl, setCanvasUrl] = useState(DEFAULT_CANVAS_URL);
  const [showToken, setShowToken] = useState(false);
  const [decryptedToken, setDecryptedToken] = useState<string>('');
  const [isFetchingToken, setIsFetchingToken] = useState(false);
  const [canvasSaved, setCanvasSaved] = useState(false);
  const [isLoading, setIsLoading] = useState(false);
  const [error, setError] = useState<string | null>(null);

  // Check if canvas is configured from DB
  const canvasConfigured = canvasTokens.length > 0;
  const activeToken = canvasTokens[0];

  // Load Canvas settings from auth context on mount
  useEffect(() => {
    if (activeToken) {
      setCanvasUrl(activeToken.canvas_domain);
      // Don't show actual token for security - just indicate it's configured
      setCanvasToken('');
    }
    // Auto-enter edit mode if no token configured
    if (!canvasConfigured) {
      setIsEditMode(true);
    }
  }, [activeToken, canvasConfigured]);

  const handleSaveCanvasSettings = async () => {
    if (!canvasToken.trim()) {
      return;
    }

    setIsLoading(true);
    setError(null);

    try {
      // If there's an existing token, revoke it first
      if (activeToken) {
        await authApi.revokeCanvasToken(activeToken.id);
      }

      // Add new token
      await authApi.addCanvasToken({
        canvas_domain: canvasUrl.trim() || DEFAULT_CANVAS_URL,
        access_token: canvasToken.trim(),
        token_type: 'PAT',
        label: 'Settings Panel',
      });

      // Refresh profile to get updated tokens
      await refreshProfile();

      // Clear the cached token so next canvas call fetches from DB
      clearCanvasTokenCache();
      clearCanvasRagTokenCache();

      setCanvasSaved(true);
      setCanvasToken(''); // Clear input after save
      setIsEditMode(false); // Exit edit mode
      setDecryptedToken(''); // Clear decrypted token cache
      setShowToken(false); // Reset show state
      setTimeout(() => setCanvasSaved(false), 3000);
    } catch (err: unknown) {
      const errorMessage = err instanceof Error ? err.message : 'Failed to save Canvas settings';
      setError(errorMessage);
    } finally {
      setIsLoading(false);
    }
  };

  const handleClearCanvasSettings = async () => {
    if (!activeToken) return;

    setIsLoading(true);
    setError(null);

    try {
      await authApi.revokeCanvasToken(activeToken.id);
      await refreshProfile();
      clearCanvasTokenCache();
      clearCanvasRagTokenCache();
      setCanvasToken('');
      setCanvasUrl(DEFAULT_CANVAS_URL);
      setIsEditMode(false);
      setDecryptedToken(''); // Clear decrypted token cache
      setShowToken(false); // Reset show state
    } catch (err: unknown) {
      const errorMessage = err instanceof Error ? err.message : 'Failed to clear Canvas settings';
      setError(errorMessage);
    } finally {
      setIsLoading(false);
    }
  };

  const handleEditClick = () => {
    setIsEditMode(true);
    setError(null);
    setCanvasToken(''); // Reset token input when entering edit mode
    setDecryptedToken(''); // Clear decrypted token cache
    setShowToken(false); // Reset show state
  };

  const handleCancelEdit = () => {
    setIsEditMode(false);
    setError(null);
    setCanvasToken('');
    setDecryptedToken(''); // Clear decrypted token cache
    setShowToken(false); // Reset show state
    // Reset URL to active token's domain
    if (activeToken) {
      setCanvasUrl(activeToken.canvas_domain);
    }
  };

  const handleToggleTokenVisibility = async () => {
    if (!showToken && !decryptedToken && canvasConfigured) {
      // Fetch the decrypted token from backend
      setIsFetchingToken(true);
      try {
        const result = await authApi.getActiveCanvasToken();
        setDecryptedToken(result.access_token);
        setShowToken(true);
      } catch (err: unknown) {
        const errorMessage = err instanceof Error ? err.message : 'Failed to fetch token';
        setError(errorMessage);
        setTimeout(() => setError(null), 3000);
      } finally {
        setIsFetchingToken(false);
      }
    } else {
      setShowToken(!showToken);
    }
  };

  return (
    <div className="settings-panel">
      <h2>
        <Settings size={24} />
        Cài đặt
      </h2>

      {/* Canvas LMS Integration Section */}
      <div className="settings-section canvas-integration-section">
        <div className="section-header">
          <h3>
            <Key size={20} />
            Canvas LMS Integration
          </h3>
          {isAuthenticated && (
            <div className="security-badge">
              <CheckCircle size={14} />
              <span>Encrypted Storage</span>
            </div>
          )}
        </div>

        {/* Auth Required Notice */}
        {!isAuthenticated && (
          <div className="auth-required-notice">
            <div className="notice-icon">
              <AlertTriangle size={24} />
            </div>
            <div className="notice-content">
              <h4>Authentication Required</h4>
              <p>Please login to configure Canvas LMS integration and securely store your access token.</p>
            </div>
          </div>
        )}

        {isAuthenticated && (
          <>
            {/* View Mode - Display current configuration */}
            {canvasConfigured && !isEditMode && (
              <>
                <div className="canvas-status-card">
                  <div className="status-header">
                    <div className="status-indicator active">
                      <CheckCircle size={18} />
                      <span>Connected</span>
                    </div>
                    <button
                      className="btn-secondary btn-sm"
                      onClick={handleEditClick}
                      disabled={isLoading}
                    >
                      <Edit2 size={14} />
                      Edit
                    </button>
                  </div>
                  <div className="status-info">
                    <div className="info-row">
                      <span className="info-label">Canvas Base URL:</span>
                      <span className="info-value">{activeToken?.canvas_domain}</span>
                    </div>
                    <div className="info-row">
                      <span className="info-label">Access Token:</span>
                      <div className="token-display-wrapper">
                        <input
                          type={showToken ? 'text' : 'password'}
                          value={showToken && decryptedToken ? decryptedToken : '••••••••••••••••••••••••••'}
                          className="input-field token-display"
                          readOnly
                          disabled
                        />
                        <button
                          type="button"
                          className="token-toggle-btn"
                          onClick={handleToggleTokenVisibility}
                          title={showToken ? 'Hide' : 'Show'}
                          disabled={isFetchingToken}
                        >
                          {isFetchingToken ? (
                            <Loader2 size={16} className="spin" />
                          ) : showToken ? (
                            <EyeOff size={16} />
                          ) : (
                            <Eye size={16} />
                          )}
                        </button>
                      </div>
                    </div>
                    <div className="info-row">
                      <span className="info-label">Token Type:</span>
                      <span className="info-value">{activeToken?.token_type || 'PAT'}</span>
                    </div>
                    {activeToken?.last_used_at && (
                      <div className="info-row">
                        <span className="info-label">Last Used:</span>
                        <span className="info-value">
                          {new Date(activeToken.last_used_at).toLocaleString()}
                        </span>
                      </div>
                    )}
                  </div>
                  
                  {/* Revoke Button in View Mode */}
                  <div className="form-actions-row" style={{ marginTop: '1rem' }}>
                    <button
                      className="btn-danger btn-revoke"
                      onClick={handleClearCanvasSettings}
                      disabled={isLoading}
                    >
                      {isLoading ? 'Revoking...' : 'Revoke Token'}
                    </button>
                  </div>
                </div>
              </>
            )}

            {/* Edit Mode - Configuration Form */}
            {isEditMode && (
              <>
                {canvasConfigured && (
                  <div className="edit-mode-notice">
                    <AlertTriangle size={16} />
                    <span>You are editing your Canvas configuration. Save to update or cancel to discard changes.</span>
                  </div>
                )}

                <div className="canvas-config-form">
                  <div className="form-group">
                    <label className="form-label">
                      Canvas Base URL
                      <span className="required">*</span>
                    </label>
                    <input
                      type="url"
                      value={canvasUrl}
                      onChange={(e) => setCanvasUrl(e.target.value)}
                      placeholder="https://lms.uet.vnu.edu.vn"
                      className="input-field"
                      disabled={isLoading}
                    />
                    <div className="field-hint">
                      <span>Your institution's Canvas instance URL</span>
                    </div>
                  </div>

                  <div className="form-group">
                    <label className="form-label">
                      {canvasConfigured ? 'New Access Token (to replace current)' : 'Access Token'}
                      <span className="required">*</span>
                    </label>
                    <div className="token-input-wrapper">
                      <input
                        type={showToken ? 'text' : 'password'}
                        value={canvasToken}
                        onChange={(e) => setCanvasToken(e.target.value)}
                        placeholder={canvasConfigured ? 'Enter new token to update' : 'Paste your Canvas access token here'}
                        className="input-field token-input"
                        disabled={isLoading}
                      />
                      <button
                        type="button"
                        className="token-toggle-btn"
                        onClick={() => setShowToken(!showToken)}
                        title={showToken ? 'Hide token' : 'Show token'}
                      >
                        {showToken ? <EyeOff size={18} /> : <Eye size={18} />}
                      </button>
                    </div>
                    <div className="field-hint">
                      <span>Generate from: Canvas → Account → Settings → New Access Token</span>
                      <a
                        href="https://community.canvaslms.com/t5/Admin-Guide/How-do-I-manage-API-access-tokens-as-an-admin/ta-p/89"
                        target="_blank"
                        rel="noopener noreferrer"
                        className="help-link"
                      >
                        <ExternalLink size={12} />
                        View Guide
                      </a>
                    </div>
                  </div>

                  {/* Action Buttons */}
                  <div className="form-actions-row">
                    <button
                      className="btn-primary btn-save"
                      onClick={handleSaveCanvasSettings}
                      disabled={!canvasToken.trim() || isLoading}
                    >
                      {isLoading ? (
                        <>
                          <Loader2 size={16} className="spin" />
                          {canvasConfigured ? 'Updating...' : 'Saving...'}
                        </>
                      ) : (
                        <>
                          <CheckCircle size={16} />
                          {canvasConfigured ? 'Update Token' : 'Save & Connect'}
                        </>
                      )}
                    </button>
                    {canvasConfigured && (
                      <button
                        className="btn-secondary"
                        onClick={handleCancelEdit}
                        disabled={isLoading}
                      >
                        <X size={16} />
                        Cancel
                      </button>
                    )}
                  </div>

                  {/* Status Messages */}
                  {error && (
                    <div className="alert alert-error">
                      <AlertTriangle size={18} />
                      <span>{error}</span>
                    </div>
                  )}

                  {canvasSaved && (
                    <div className="alert alert-success">
                      <CheckCircle size={18} />
                      <span>Canvas token {canvasConfigured ? 'updated' : 'saved'} successfully!</span>
                    </div>
                  )}
                </div>
              </>
            )}
          </>
        )}
      </div>

      {/* AI Model Section */}
      <div className="settings-section">
        <h3>
          <Cpu size={20} />
          Model AI
        </h3>

        {/* Provider Badge */}
        <div className="provider-badge-wrapper">
          <span className={`provider-badge provider-${config?.llm_provider || 'ollama'}`}>
            {config?.llm_provider === 'groq' ? '⚡ Groq Cloud' : '🖥️ Ollama Local'}
          </span>
          {config?.llm_provider === 'groq' && (
            <span className="provider-hint">Inference nhanh qua Groq LPU</span>
          )}
        </div>

        <div className="form-group">
          <label>Chọn model:</label>
          {showModelSelector(config?.llm_provider || 'ollama') ? (
            <select value={model} onChange={(e) => setModel(e.target.value)}>
              {(getEnabledModels(config?.llm_provider || 'ollama').length > 0
                ? getEnabledModels(config?.llm_provider || 'ollama')
                : config?.available_models || []
              ).map((m) => (
                <option key={m} value={m}>
                  {m}
                </option>
              ))}
            </select>
          ) : (
            <span className="provider-label-static">{model}</span>
          )}
        </div>

        <div className="form-group">
          <label>Số vòng lặp tối đa:</label>
          <input
            type="range"
            min={5}
            max={20}
            value={maxIterations}
            onChange={(e) => setMaxIterations(parseInt(e.target.value))}
          />
          <span className="range-value">{maxIterations}</span>
        </div>
      </div>

      {/* System Info Section */}
      <div className="settings-section">
        <h3>Thông tin hệ thống</h3>
        <div className="info-list">
          <div className="info-item">
            <span>API URL:</span>
            <code>http://localhost:8080</code>
          </div>
          <div className="info-item">
            <span>LLM Provider:</span>
            <code className={`provider-code provider-code-${config?.llm_provider || 'ollama'}`}>
              {config?.llm_provider === 'groq' ? 'Groq Cloud' : 'Ollama Local'}
            </code>
          </div>
          <div className="info-item">
            <span>Model mặc định:</span>
            <code>{config?.default_model}</code>
          </div>
          <div className="info-item">
            <span>Groq API:</span>
            <code>{config?.groq_available ? '✅ Configured' : '❌ Not configured'}</code>
          </div>
          <div className="info-item">
            <span>Phiên bản:</span>
            <code>1.0.0</code>
          </div>
        </div>
      </div>
    </div>
  );
};

export default SettingsPanel;
