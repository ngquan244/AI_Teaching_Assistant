/**
 * Admin Model Management
 * Allows admins to enable/disable LLM providers and individual models.
 * Disabled providers/models are hidden from the teacher UI.
 * When only 1 option remains, selection UI is auto-hidden.
 */
import React, { useState, useEffect, useCallback } from 'react';
import {
  ToggleLeft,
  ToggleRight,
  Loader2,
  Save,
  Monitor,
  Zap,
  AlertCircle,
  CheckCircle,
  Cpu,
} from 'lucide-react';
import {
  getAdminModelConfig,
  updateModelConfig,
  type ModelConfig,
} from '../../api/admin';

// Map provider key → icon
const PROVIDER_ICONS: Record<string, typeof Monitor> = {
  ollama: Monitor,
  groq: Zap,
};

const AdminModels: React.FC = () => {
  const [config, setConfig] = useState<ModelConfig | null>(null);
  const [localProviders, setLocalProviders] = useState<Record<string, boolean>>({});
  const [localModels, setLocalModels] = useState<Record<string, Record<string, boolean>>>({});
  const [loading, setLoading] = useState(true);
  const [saving, setSaving] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [success, setSuccess] = useState<string | null>(null);
  const [hasChanges, setHasChanges] = useState(false);

  const fetchConfig = useCallback(async () => {
    try {
      setLoading(true);
      const data = await getAdminModelConfig();
      setConfig(data);
      setLocalProviders({ ...data.providers });
      // deep clone models
      const cloned: Record<string, Record<string, boolean>> = {};
      for (const [p, m] of Object.entries(data.models)) {
        cloned[p] = { ...m };
      }
      setLocalModels(cloned);
      setHasChanges(false);
    } catch {
      setError('Không thể tải cấu hình model');
    } finally {
      setLoading(false);
    }
  }, []);

  useEffect(() => {
    fetchConfig();
  }, [fetchConfig]);

  const checkChanges = useCallback(
    (providers: Record<string, boolean>, models: Record<string, Record<string, boolean>>) => {
      if (!config) return false;
      for (const p of config.all_providers) {
        if (providers[p] !== config.providers[p]) return true;
      }
      for (const [provider, modelMap] of Object.entries(config.models)) {
        for (const [model, enabled] of Object.entries(modelMap)) {
          if (models[provider]?.[model] !== enabled) return true;
        }
      }
      return false;
    },
    [config],
  );

  const handleToggleProvider = (provider: string) => {
    setLocalProviders((prev) => {
      const updated = { ...prev, [provider]: !prev[provider] };
      setHasChanges(checkChanges(updated, localModels));
      return updated;
    });
    setSuccess(null);
  };

  const handleToggleModel = (provider: string, model: string) => {
    setLocalModels((prev) => {
      const updated = {
        ...prev,
        [provider]: { ...prev[provider], [model]: !prev[provider]?.[model] },
      };
      setHasChanges(checkChanges(localProviders, updated));
      return updated;
    });
    setSuccess(null);
  };

  const handleSave = async () => {
    try {
      setSaving(true);
      setError(null);
      const updated = await updateModelConfig({
        providers: localProviders,
        models: localModels,
      });
      setConfig(updated);
      setLocalProviders({ ...updated.providers });
      const cloned: Record<string, Record<string, boolean>> = {};
      for (const [p, m] of Object.entries(updated.models)) {
        cloned[p] = { ...m };
      }
      setLocalModels(cloned);
      setHasChanges(false);
      setSuccess('Cấu hình model đã được cập nhật thành công!');
      setTimeout(() => setSuccess(null), 3000);
    } catch {
      setError('Không thể lưu cấu hình model');
    } finally {
      setSaving(false);
    }
  };

  const handleReset = () => {
    if (config) {
      setLocalProviders({ ...config.providers });
      const cloned: Record<string, Record<string, boolean>> = {};
      for (const [p, m] of Object.entries(config.models)) {
        cloned[p] = { ...m };
      }
      setLocalModels(cloned);
      setHasChanges(false);
      setSuccess(null);
    }
  };

  const enabledProviderCount = Object.values(localProviders).filter(Boolean).length;
  const totalModelCount = Object.values(localModels).reduce(
    (sum, m) => sum + Object.values(m).filter(Boolean).length,
    0,
  );
  const totalModels = Object.values(localModels).reduce(
    (sum, m) => sum + Object.keys(m).length,
    0,
  );

  if (loading) {
    return (
      <div className="admin-loading">
        <Loader2 className="spin" size={40} />
        <p>Đang tải cấu hình model...</p>
      </div>
    );
  }

  return (
    <div className="admin-page">
      <div className="admin-page-header">
        <div>
          <h2>Quản lý Model AI</h2>
          <p className="admin-page-subtitle">
            Bật / tắt các LLM provider và model. Provider hoặc model bị tắt sẽ{' '}
            <strong>hoàn toàn ẩn</strong> khỏi giao diện Teacher.
            Nếu chỉ còn 1 lựa chọn, UI chọn model/provider sẽ tự động ẩn.
          </p>
        </div>
        <div className="admin-page-actions">
          <span className="panels-counter">
            {enabledProviderCount} provider · {totalModelCount}/{totalModels} model
          </span>
          {hasChanges && (
            <button className="admin-btn admin-btn-secondary" onClick={handleReset}>
              Hủy thay đổi
            </button>
          )}
          <button
            className="admin-btn admin-btn-primary"
            onClick={handleSave}
            disabled={!hasChanges || saving}
          >
            {saving ? (
              <>
                <Loader2 className="spin" size={16} />
                <span>Đang lưu...</span>
              </>
            ) : (
              <>
                <Save size={16} />
                <span>Lưu cấu hình</span>
              </>
            )}
          </button>
        </div>
      </div>

      {error && (
        <div className="admin-alert admin-alert-error">
          <AlertCircle size={18} />
          <span>{error}</span>
        </div>
      )}

      {success && (
        <div className="admin-alert admin-alert-success">
          <CheckCircle size={18} />
          <span>{success}</span>
        </div>
      )}

      {/* Provider + Model cards */}
      <div className="model-providers-list">
        {config?.all_providers.map((provider) => {
          const ProvIcon = PROVIDER_ICONS[provider] || Cpu;
          const provEnabled = localProviders[provider] ?? true;
          const provLabel = config.provider_labels[provider] || provider;
          const provDesc = config.provider_descriptions[provider] || '';
          const models = config.all_models[provider] || [];

          return (
            <div
              key={provider}
              className={`model-provider-card ${provEnabled ? 'provider-enabled' : 'provider-disabled'}`}
            >
              {/* Provider header */}
              <div className="provider-card-header">
                <div className="provider-card-left">
                  <div className={`provider-card-icon ${provider}`}>
                    <ProvIcon size={24} />
                  </div>
                  <div>
                    <h3 className="provider-card-title">{provLabel}</h3>
                    <p className="provider-card-desc">{provDesc}</p>
                  </div>
                </div>
                <button
                  className="panel-toggle-btn"
                  onClick={() => handleToggleProvider(provider)}
                  title={provEnabled ? 'Tắt provider' : 'Bật provider'}
                >
                  {provEnabled ? (
                    <ToggleRight size={36} className="toggle-on" />
                  ) : (
                    <ToggleLeft size={36} className="toggle-off" />
                  )}
                </button>
              </div>

              {/* Models grid */}
              <div className={`provider-models-grid ${!provEnabled ? 'models-dimmed' : ''}`}>
                {models.map((model) => {
                  const modelEnabled = localModels[provider]?.[model] ?? true;
                  const modelLabel = config.model_labels[model] || model;
                  const effectiveEnabled = provEnabled && modelEnabled;

                  return (
                    <div
                      key={model}
                      className={`model-item ${effectiveEnabled ? 'model-enabled' : 'model-disabled'}`}
                    >
                      <div className="model-item-info">
                        <Cpu size={16} className="model-item-icon" />
                        <div>
                          <span className="model-item-label">{modelLabel}</span>
                          <span className="model-item-id">{model}</span>
                        </div>
                      </div>
                      <button
                        className="model-toggle-btn"
                        onClick={() => handleToggleModel(provider, model)}
                        disabled={!provEnabled}
                        title={modelEnabled ? 'Tắt model' : 'Bật model'}
                      >
                        {modelEnabled ? (
                          <ToggleRight size={28} className={provEnabled ? 'toggle-on' : 'toggle-off'} />
                        ) : (
                          <ToggleLeft size={28} className="toggle-off" />
                        )}
                      </button>
                    </div>
                  );
                })}
              </div>
            </div>
          );
        })}
      </div>
    </div>
  );
};

export default AdminModels;
