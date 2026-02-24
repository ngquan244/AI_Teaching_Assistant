/**
 * Admin Tool Management
 * Allows admins to enable/disable agent tools.
 * Disabled tools are NOT available to the AI agent at all.
 */
import React, { useState, useEffect, useCallback } from 'react';
import {
  ToggleLeft,
  ToggleRight,
  Loader2,
  Save,
  AlertCircle,
  CheckCircle,
  Wrench,
  Calculator,
  FileText,
  BarChart3,
  GraduationCap,
} from 'lucide-react';
import {
  getAdminToolConfig,
  updateToolConfig,
  type ToolConfig,
} from '../../api/admin';

// Map tool name → icon
const TOOL_ICONS: Record<string, React.ReactNode> = {
  execute_notebook: <GraduationCap size={20} />,
  calculator: <Calculator size={20} />,
  quiz_generator: <FileText size={20} />,
  summarize_exam_results: <BarChart3 size={20} />,
};

const AdminTools: React.FC = () => {
  const [config, setConfig] = useState<ToolConfig | null>(null);
  const [localTools, setLocalTools] = useState<Record<string, boolean>>({});
  const [loading, setLoading] = useState(true);
  const [saving, setSaving] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [success, setSuccess] = useState<string | null>(null);
  const [hasChanges, setHasChanges] = useState(false);

  const fetchConfig = useCallback(async () => {
    try {
      setLoading(true);
      const data = await getAdminToolConfig();
      setConfig(data);
      setLocalTools({ ...data.tools });
      setHasChanges(false);
    } catch {
      setError('Không thể tải cấu hình tools');
    } finally {
      setLoading(false);
    }
  }, []);

  useEffect(() => {
    fetchConfig();
  }, [fetchConfig]);

  const checkChanges = useCallback(
    (tools: Record<string, boolean>) => {
      if (!config) return false;
      for (const t of config.all_tools) {
        if (tools[t] !== config.tools[t]) return true;
      }
      return false;
    },
    [config],
  );

  const handleToggle = (tool: string) => {
    setLocalTools((prev) => {
      const updated = { ...prev, [tool]: !prev[tool] };
      setHasChanges(checkChanges(updated));
      return updated;
    });
    setSuccess(null);
  };

  const handleSave = async () => {
    try {
      setSaving(true);
      setError(null);
      const updated = await updateToolConfig({ tools: localTools });
      setConfig(updated);
      setLocalTools({ ...updated.tools });
      setHasChanges(false);
      setSuccess('Cấu hình tools đã được cập nhật! Agent sẽ áp dụng ngay ở lần chat tiếp theo.');
      setTimeout(() => setSuccess(null), 4000);
    } catch {
      setError('Không thể lưu cấu hình tools');
    } finally {
      setSaving(false);
    }
  };

  const handleReset = () => {
    if (config) {
      setLocalTools({ ...config.tools });
      setHasChanges(false);
      setSuccess(null);
    }
  };

  const enabledCount = Object.values(localTools).filter(Boolean).length;
  const totalCount = Object.keys(localTools).length;

  if (loading) {
    return (
      <div className="admin-loading">
        <Loader2 className="spin" size={40} />
        <p>Đang tải cấu hình tools...</p>
      </div>
    );
  }

  return (
    <div className="admin-page">
      <div className="admin-page-header">
        <div>
          <h2>Quản lý Agent Tools</h2>
          <p className="admin-page-subtitle">
            Bật / tắt các công cụ mà AI Agent có thể sử dụng. Tool bị tắt sẽ{' '}
            <strong>không được bind</strong> vào LLM — agent hoàn toàn không thể gọi tool đó.
          </p>
        </div>
        <div className="admin-page-actions">
          <span className="panels-counter">
            {enabledCount}/{totalCount} tools đang bật
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

      {/* Tool Cards */}
      <div className="tool-cards-list">
        {config?.all_tools.map((tool) => {
          const enabled = localTools[tool] ?? true;
          const label = config.tool_labels[tool] || tool;
          const desc = config.tool_descriptions[tool] || '';
          const icon = TOOL_ICONS[tool] || <Wrench size={20} />;

          return (
            <div
              key={tool}
              className={`tool-card ${enabled ? 'tool-enabled' : 'tool-disabled'}`}
            >
              <div className="tool-card-left">
                <div className={`tool-card-icon ${enabled ? 'active' : ''}`}>
                  {icon}
                </div>
                <div className="tool-card-info">
                  <h4 className="tool-card-name">{label}</h4>
                  <p className="tool-card-desc">{desc}</p>
                  <code className="tool-card-id">{tool}</code>
                </div>
              </div>
              <button
                className="panel-toggle-btn"
                onClick={() => handleToggle(tool)}
                title={enabled ? 'Tắt tool' : 'Bật tool'}
              >
                {enabled ? (
                  <ToggleRight size={36} className="toggle-on" />
                ) : (
                  <ToggleLeft size={36} className="toggle-off" />
                )}
              </button>
            </div>
          );
        })}
      </div>

      {/* Info box */}
      <div className="tool-info-box">
        <AlertCircle size={16} />
        <div>
          <strong>Lưu ý:</strong> Khi tắt một tool, agent sẽ không thể sử dụng tính năng đó.
          Nếu người dùng yêu cầu tính năng đã bị tắt, AI sẽ tự động thông báo rằng tính năng
          đang tạm thời bị khóa bởi quản trị viên. Gợi ý chat trong giao diện cũng sẽ tự ẩn
          các tính năng không khả dụng.
        </div>
      </div>
    </div>
  );
};

export default AdminTools;
