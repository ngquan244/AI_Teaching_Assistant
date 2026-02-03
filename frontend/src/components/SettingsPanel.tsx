import React, { useState, useEffect } from 'react';
import { useApp } from '../context/AppContext';
import {
  Settings,
  Cpu,
  Key,
  Eye,
  EyeOff,
  CheckCircle,
  AlertTriangle,
  ExternalLink,
} from 'lucide-react';
import {
  getCanvasSettings,
  saveCanvasSettings,
  clearCanvasSettings,
} from '../utils/canvasStorage';

const DEFAULT_CANVAS_URL = 'https://lms.uet.vnu.edu.vn';

const SettingsPanel: React.FC = () => {
  const { config, model, setModel, maxIterations, setMaxIterations } = useApp();

  // Canvas settings state
  const [canvasToken, setCanvasToken] = useState('');
  const [canvasUrl, setCanvasUrl] = useState(DEFAULT_CANVAS_URL);
  const [showToken, setShowToken] = useState(false);
  const [canvasSaved, setCanvasSaved] = useState(false);
  const [canvasConfigured, setCanvasConfigured] = useState(false);

  // Load Canvas settings on mount
  useEffect(() => {
    const settings = getCanvasSettings();
    if (settings) {
      setCanvasToken(settings.accessToken);
      setCanvasUrl(settings.baseUrl);
      setCanvasConfigured(true);
    }
  }, []);

  const handleSaveCanvasSettings = () => {
    if (!canvasToken.trim()) {
      return;
    }

    saveCanvasSettings({
      accessToken: canvasToken.trim(),
      baseUrl: canvasUrl.trim() || DEFAULT_CANVAS_URL,
    });

    setCanvasSaved(true);
    setCanvasConfigured(true);
    setTimeout(() => setCanvasSaved(false), 3000);
  };

  const handleClearCanvasSettings = () => {
    clearCanvasSettings();
    setCanvasToken('');
    setCanvasUrl(DEFAULT_CANVAS_URL);
    setCanvasConfigured(false);
  };

  return (
    <div className="settings-panel">
      <h2>
        <Settings size={24} />
        Cài đặt
      </h2>

      {/* Canvas LMS Integration Section */}
      <div className="settings-section">
        <h3>
          <Key size={20} />
          Canvas LMS Integration
        </h3>

        {/* Security Warning */}
        <div className="security-warning">
          <AlertTriangle size={16} />
          <span>
            <strong>Testing Mode:</strong> Token stored in browser localStorage.
            Not secure for production use.
          </span>
        </div>

        <div className="form-group">
          <label>Canvas Base URL:</label>
          <input
            type="url"
            value={canvasUrl}
            onChange={(e) => setCanvasUrl(e.target.value)}
            placeholder="https://lms.uet.vnu.edu.vn"
            className="input-field"
          />
          <span className="hint">
            Your institution's Canvas URL (e.g., https://yourschool.instructure.com)
          </span>
        </div>

        <div className="form-group">
          <label>Access Token:</label>
          <div className="input-with-toggle">
            <input
              type={showToken ? 'text' : 'password'}
              value={canvasToken}
              onChange={(e) => setCanvasToken(e.target.value)}
              placeholder="Enter your Canvas access token"
              className="input-field"
            />
            <button
              type="button"
              className="btn-icon-inline"
              onClick={() => setShowToken(!showToken)}
              title={showToken ? 'Hide token' : 'Show token'}
            >
              {showToken ? <EyeOff size={18} /> : <Eye size={18} />}
            </button>
          </div>
          <span className="hint">
            Generate from Canvas → Account → Settings → New Access Token
            <a
              href="https://community.canvaslms.com/t5/Admin-Guide/How-do-I-manage-API-access-tokens-as-an-admin/ta-p/89"
              target="_blank"
              rel="noopener noreferrer"
              className="hint-link"
            >
              <ExternalLink size={12} /> Learn more
            </a>
          </span>
        </div>

        <div className="form-actions">
          <button
            className="btn-primary"
            onClick={handleSaveCanvasSettings}
            disabled={!canvasToken.trim()}
          >
            Save Canvas Settings
          </button>
          {canvasConfigured && (
            <button
              className="btn-secondary danger"
              onClick={handleClearCanvasSettings}
            >
              Clear Token
            </button>
          )}
        </div>

        {canvasSaved && (
          <div className="result-message success">
            <CheckCircle size={18} />
            Canvas settings saved successfully!
          </div>
        )}

        {canvasConfigured && !canvasSaved && (
          <div className="canvas-status connected">
            <CheckCircle size={16} />
            <span>Canvas token configured</span>
          </div>
        )}
      </div>

      {/* AI Model Section */}
      <div className="settings-section">
        <h3>
          <Cpu size={20} />
          Model AI
        </h3>
        <div className="form-group">
          <label>Chọn model:</label>
          <select value={model} onChange={(e) => setModel(e.target.value)}>
            {config?.available_models.map((m) => (
              <option key={m} value={m}>
                {m}
              </option>
            ))}
          </select>
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
            <code>http://localhost:8000</code>
          </div>
          <div className="info-item">
            <span>Model mặc định:</span>
            <code>{config?.default_model}</code>
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
