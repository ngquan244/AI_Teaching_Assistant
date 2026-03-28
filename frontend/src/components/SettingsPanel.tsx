import React, { useState, useEffect, useCallback } from 'react';
import { useNavigate } from 'react-router-dom';
import { useApp } from '../context/AppContext';
import { useAuth } from '../context/AuthContext';
import { authApi } from '../api/auth';
import { groqKeyApi, type GroqKeyStatus } from '../api/groqKey';
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
  BookOpen,
  Loader2,
  Edit2,
  X,
  Cloud,
  Database,
  Trash2,
  Save,
} from 'lucide-react';
import PanelHelpButton from './PanelHelpButton';

const DEFAULT_CANVAS_URL = 'https://lms.uet.vnu.edu.vn';

const SettingsPanel: React.FC = () => {
  const navigate = useNavigate();
  const { model } = useApp();
  const { canvasTokens, refreshProfile, isAuthenticated, user } = useAuth();
  const isAdmin = user?.role === 'ADMIN';

  // Canvas settings state
  const [isEditMode, setIsEditMode] = useState(false);
  const [canvasToken, setCanvasToken] = useState('');
  const [canvasUrl, setCanvasUrl] = useState(DEFAULT_CANVAS_URL);
  const [showToken, setShowToken] = useState(false);
  const [canvasSaved, setCanvasSaved] = useState(false);
  const [isLoading, setIsLoading] = useState(false);
  const [error, setError] = useState<string | null>(null);

  // Check if canvas is configured from DB
  const canvasConfigured = canvasTokens.length > 0;
  const activeToken = canvasTokens[0];

  // ── Groq API Key state (admin only) ──
  const [groqKeyStatus, setGroqKeyStatus] = useState<GroqKeyStatus | null>(null);
  const [groqKeyInput, setGroqKeyInput] = useState('');
  const [showGroqKey, setShowGroqKey] = useState(false);
  const [groqKeyLoading, setGroqKeyLoading] = useState(false);
  const [groqKeyError, setGroqKeyError] = useState<string | null>(null);
  const [groqKeySaved, setGroqKeySaved] = useState(false);
  const [groqKeyEditMode, setGroqKeyEditMode] = useState(false);

  const fetchGroqKeyStatus = useCallback(async () => {
    if (!isAdmin) return;
    try {
      const status = await groqKeyApi.getStatus();
      setGroqKeyStatus(status);
    } catch {
      // Non-fatal — admin may not have access in dev
    }
  }, [isAdmin]);

  useEffect(() => {
    fetchGroqKeyStatus();
  }, [fetchGroqKeyStatus]);

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
    setShowToken(false); // Reset show state
  };

  const handleCancelEdit = () => {
    setIsEditMode(false);
    setError(null);
    setCanvasToken('');
    setShowToken(false); // Reset show state
    // Reset URL to active token's domain
    if (activeToken) {
      setCanvasUrl(activeToken.canvas_domain);
    }
  };

  return (
    <div className="settings-panel">
      <div style={{ display: 'flex', alignItems: 'center', justifyContent: 'space-between' }}>
        <h2>
          <Settings size={24} />
          Cài đặt
        </h2>
        <PanelHelpButton panelKey="settings" />
      </div>

      {/* Canvas LMS Integration Section */}
      <div className="settings-section canvas-integration-section">
        <div className="section-header">
          <h3>
            <Key size={20} />
            Canvas LMS - Kết nối
          </h3>
          {isAuthenticated && (
            <div className="security-badge">
              <CheckCircle size={14} />
              <span>Bảo mật</span>
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
              <h4>Yêu cầu đăng nhập</h4>
              <p>Vui lòng đăng nhập để cấu hình kết nối Canvas LMS và lưu trữ access token an toàn.</p>
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
                      <span className="info-value">Stored securely on server</span>
                    </div>
                    <div className="info-row">
                      <span className="info-label">Loại xác thực:</span>
                      <span className="info-value">{activeToken?.token_type === 'PAT' ? 'Token cá nhân' : (activeToken?.token_type || 'Token cá nhân')}</span>
                    </div>
                    {activeToken?.last_used_at && (
                      <div className="info-row">
                        <span className="info-label">Sử dụng lần cuối:</span>
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
                      <button
                        type="button"
                        className="help-link"
                        onClick={() => navigate('/guide/settings')}
                        style={{ background: 'none', border: 'none', cursor: 'pointer', padding: 0 }}
                      >
                        <BookOpen size={12} />
                        Xem hướng dẫn
                      </button>
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

      {/* Groq API Key Section — Admin Only */}
      {isAdmin && (
        <div className="settings-section canvas-integration-section">
          <div className="section-header">
            <h3>
              <Cloud size={20} />
              Groq API Key
            </h3>
            {groqKeyStatus?.has_key && (
              <div className="security-badge">
                <CheckCircle size={14} />
                <span>{groqKeyStatus.source === 'db' ? 'DB (mã hoá)' : 'Biến môi trường'}</span>
              </div>
            )}
          </div>

          {/* Status View (not editing) */}
          {!groqKeyEditMode && (
            <div className="canvas-status-card">
              <div className="status-header">
                <div className={`status-indicator ${groqKeyStatus?.has_key ? 'active' : ''}`}>
                  {groqKeyStatus?.has_key ? (
                    <>
                      <CheckCircle size={18} />
                      <span>Đã cấu hình</span>
                    </>
                  ) : (
                    <>
                      <AlertTriangle size={18} />
                      <span>Chưa cấu hình</span>
                    </>
                  )}
                </div>
                <button
                  className="btn-secondary btn-sm"
                  onClick={() => {
                    setGroqKeyEditMode(true);
                    setGroqKeyError(null);
                    setGroqKeyInput('');
                    setShowGroqKey(false);
                  }}
                >
                  <Edit2 size={14} />
                  {groqKeyStatus?.has_key ? 'Thay đổi' : 'Thêm Key'}
                </button>
              </div>

              {groqKeyStatus?.has_key && (
                <div className="status-info">
                  <div className="info-row">
                    <span className="info-label">Nguồn:</span>
                    <span className="info-value">
                      {groqKeyStatus.source === 'db' ? (
                        <><Database size={14} style={{ marginRight: 4, verticalAlign: 'middle' }} /> Database (mã hoá Fernet)</>
                      ) : (
                        <><Settings size={14} style={{ marginRight: 4, verticalAlign: 'middle' }} /> Biến môi trường (.env)</>
                      )}
                    </span>
                  </div>
                  <div className="info-row">
                    <span className="info-label">API Key:</span>
                    <span className="info-value" style={{ fontFamily: 'monospace' }}>
                      {groqKeyStatus.masked_key || '***'}
                    </span>
                  </div>
                  {groqKeyStatus.updated_at && (
                    <div className="info-row">
                      <span className="info-label">Cập nhật:</span>
                      <span className="info-value">
                        {new Date(groqKeyStatus.updated_at).toLocaleString()}
                      </span>
                    </div>
                  )}

                  {/* Delete button — only if key is in DB */}
                  {groqKeyStatus.source === 'db' && (
                    <div className="form-actions-row" style={{ marginTop: '1rem' }}>
                      <button
                        className="btn-danger btn-revoke"
                        onClick={async () => {
                          setGroqKeyLoading(true);
                          setGroqKeyError(null);
                          try {
                            await groqKeyApi.deleteKey();
                            await fetchGroqKeyStatus();
                          } catch (err: unknown) {
                            setGroqKeyError(err instanceof Error ? err.message : 'Xoá thất bại');
                          } finally {
                            setGroqKeyLoading(false);
                          }
                        }}
                        disabled={groqKeyLoading}
                      >
                        <Trash2 size={14} />
                        {groqKeyLoading ? 'Đang xoá...' : 'Xoá key khỏi DB'}
                      </button>
                    </div>
                  )}
                </div>
              )}

              {!groqKeyStatus?.has_key && (
                <div className="edit-mode-notice" style={{ marginTop: '0.75rem' }}>
                  <AlertTriangle size={16} />
                  <span>
                    Chưa có Groq API key. Hệ thống cần key để sử dụng Groq Cloud.
                    Lấy key miễn phí tại{' '}
                    <a href="https://console.groq.com/keys" target="_blank" rel="noopener noreferrer">
                      console.groq.com
                    </a>.
                  </span>
                </div>
              )}
            </div>
          )}

          {/* Edit Mode */}
          {groqKeyEditMode && (
            <div className="canvas-config-form">
              <div className="form-group">
                <label className="form-label">
                  Groq API Key
                  <span className="required">*</span>
                </label>
                <div className="token-input-wrapper">
                  <input
                    type={showGroqKey ? 'text' : 'password'}
                    value={groqKeyInput}
                    onChange={(e) => setGroqKeyInput(e.target.value)}
                    placeholder="gsk_..."
                    className="input-field token-input"
                    disabled={groqKeyLoading}
                  />
                  <button
                    type="button"
                    className="token-toggle-btn"
                    onClick={() => setShowGroqKey(!showGroqKey)}
                    title={showGroqKey ? 'Ẩn' : 'Hiện'}
                  >
                    {showGroqKey ? <EyeOff size={18} /> : <Eye size={18} />}
                  </button>
                </div>
                <div className="field-hint">
                  <span>
                    Lấy key tại{' '}
                    <a href="https://console.groq.com/keys" target="_blank" rel="noopener noreferrer">
                      console.groq.com/keys
                    </a>
                    {' '}— Key sẽ được mã hoá và lưu an toàn trong database.
                  </span>
                </div>
              </div>

              <div className="form-actions-row">
                <button
                  className="btn-primary btn-save"
                  onClick={async () => {
                    if (!groqKeyInput.trim()) return;
                    setGroqKeyLoading(true);
                    setGroqKeyError(null);
                    try {
                      await groqKeyApi.updateKey(groqKeyInput.trim());
                      setGroqKeySaved(true);
                      setGroqKeyEditMode(false);
                      setGroqKeyInput('');
                      setShowGroqKey(false);
                      await fetchGroqKeyStatus();
                      setTimeout(() => setGroqKeySaved(false), 3000);
                    } catch (err: unknown) {
                      const msg = err instanceof Error ? err.message : 'Lưu thất bại';
                      // Try to extract detail from API response
                      const detail = (err as { response?: { data?: { detail?: string } } })?.response?.data?.detail;
                      setGroqKeyError(detail || msg);
                    } finally {
                      setGroqKeyLoading(false);
                    }
                  }}
                  disabled={!groqKeyInput.trim() || groqKeyLoading}
                >
                  {groqKeyLoading ? (
                    <>
                      <Loader2 size={16} className="spin" />
                      Đang kiểm tra &amp; lưu...
                    </>
                  ) : (
                    <>
                      <Save size={16} />
                      Lưu API Key
                    </>
                  )}
                </button>
                <button
                  className="btn-secondary"
                  onClick={() => {
                    setGroqKeyEditMode(false);
                    setGroqKeyError(null);
                    setGroqKeyInput('');
                    setShowGroqKey(false);
                  }}
                  disabled={groqKeyLoading}
                >
                  <X size={16} />
                  Huỷ
                </button>
              </div>

              {groqKeyError && (
                <div className="alert alert-error">
                  <AlertTriangle size={18} />
                  <span>{groqKeyError}</span>
                </div>
              )}

              {groqKeySaved && (
                <div className="alert alert-success">
                  <CheckCircle size={18} />
                  <span>Groq API key đã được lưu thành công!</span>
                </div>
              )}
            </div>
          )}
        </div>
      )}

      {/* AI Model Section - Admin Only */}
      {isAdmin && (
        <div className="settings-section">
          <h3>
            <Cpu size={20} />
            Model AI
          </h3>

          {/* Provider Badge */}
          <div className="provider-badge-wrapper">
            <span className="provider-badge provider-groq">
              ⚡ Groq Cloud
            </span>
            <span className="provider-hint">Xử lý nhanh</span>
          </div>

          <div className="form-group">
            <label>Model hiện tại:</label>
            <span className="provider-label-static">{model}</span>
          </div>
        </div>
      )}


    </div>
  );
};

export default SettingsPanel;
