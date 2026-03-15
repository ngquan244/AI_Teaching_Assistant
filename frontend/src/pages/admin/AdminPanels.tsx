/**
 * Admin Panel Management
 * Allows admins to enable/disable panels for teacher UI.
 * Disabled panels are completely hidden from the teacher sidebar.
 */
import React, { useState, useEffect, useCallback } from 'react';
import {
  ToggleLeft,
  ToggleRight,
  Loader2,
  Save,
  FileText,
  FolderOpen,
  PenSquare,
  PlayCircle,
  PieChart,
  Settings,
  AlertCircle,
  CheckCircle,
  BookOpen,
} from 'lucide-react';
import { getAdminPanelConfig, updatePanelConfig, type PanelConfig } from '../../api/admin';

// Map panel key → icon
const PANEL_ICONS: Record<string, typeof FileText> = {
  document_rag: FileText,
  canvas: FolderOpen,
  canvas_quiz: PenSquare,
  canvas_simulation: PlayCircle,
  canvas_results: PieChart,
  guide: BookOpen,
  settings: Settings,
};

// Panel descriptions for better UX
const PANEL_DESCRIPTIONS: Record<string, string> = {
  document_rag: 'Hỏi đáp dựa trên tài liệu (RAG)',
  canvas: 'Kết nối và quản lý Canvas LMS',
  canvas_quiz: 'Tạo quiz trên Canvas từ tài liệu',
  canvas_simulation: 'Tạo test student và giả lập nộp bài quiz trên Canvas',
  canvas_results: 'Tổng hợp kết quả quiz, điểm khóa học và xuất báo cáo Excel/CSV',
  guide: 'Hướng dẫn sử dụng hệ thống',
  settings: 'Cấu hình model AI, provider và các tùy chọn',
};

const AdminPanels: React.FC = () => {
  const [config, setConfig] = useState<PanelConfig | null>(null);
  const [localPanels, setLocalPanels] = useState<Record<string, boolean>>({});
  const [loading, setLoading] = useState(true);
  const [saving, setSaving] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [success, setSuccess] = useState<string | null>(null);
  const [hasChanges, setHasChanges] = useState(false);

  const fetchConfig = useCallback(async () => {
    try {
      setLoading(true);
      const data = await getAdminPanelConfig();
      setConfig(data);
      setLocalPanels({ ...data.panels });
      setHasChanges(false);
    } catch {
      setError('Không thể tải cấu hình panel');
    } finally {
      setLoading(false);
    }
  }, []);

  useEffect(() => {
    fetchConfig();
  }, [fetchConfig]);

  const handleToggle = (key: string) => {
    setLocalPanels((prev) => {
      const updated = { ...prev, [key]: !prev[key] };
      // Check if changed from original
      if (config) {
        const changed = Object.keys(updated).some(
          (k) => updated[k] !== config.panels[k],
        );
        setHasChanges(changed);
      }
      return updated;
    });
    setSuccess(null);
  };

  const handleSave = async () => {
    try {
      setSaving(true);
      setError(null);
      const updated = await updatePanelConfig({ panels: localPanels });
      setConfig(updated);
      setLocalPanels({ ...updated.panels });
      setHasChanges(false);
      setSuccess('Cấu hình panel đã được cập nhật thành công!');
      setTimeout(() => setSuccess(null), 3000);
    } catch {
      setError('Không thể lưu cấu hình panel');
    } finally {
      setSaving(false);
    }
  };

  const handleReset = () => {
    if (config) {
      setLocalPanels({ ...config.panels });
      setHasChanges(false);
      setSuccess(null);
    }
  };

  const enabledCount = Object.values(localPanels).filter(Boolean).length;
  const totalCount = Object.keys(localPanels).length;

  if (loading) {
    return (
      <div className="admin-loading">
        <Loader2 className="spin" size={40} />
        <p>Đang tải cấu hình panel...</p>
      </div>
    );
  }

  return (
    <div className="admin-page">
      <div className="admin-page-header">
        <div>
          <h2>Quản lý Panel</h2>
          <p className="admin-page-subtitle">
            Bật / tắt các panel hiển thị trên giao diện Teacher.
            Panel bị tắt sẽ <strong>hoàn toàn ẩn</strong> khỏi sidebar và không thể truy cập.
          </p>
        </div>
        <div className="admin-page-actions">
          <span className="panels-counter">
            {enabledCount}/{totalCount} panel đang bật
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

      <div className="panels-grid">
        {config?.all_panels.map((key) => {
          const Icon = PANEL_ICONS[key] || Settings;
          const label = config.labels[key] || key;
          const description = PANEL_DESCRIPTIONS[key] || '';
          const enabled = localPanels[key] ?? true;

          return (
            <div
              key={key}
              className={`panel-card ${enabled ? 'panel-card-enabled' : 'panel-card-disabled'}`}
            >
              <div className="panel-card-header">
                <div className="panel-card-icon">
                  <Icon size={24} />
                </div>
                <button
                  className="panel-toggle-btn"
                  onClick={() => handleToggle(key)}
                  title={enabled ? 'Tắt panel' : 'Bật panel'}
                >
                  {enabled ? (
                    <ToggleRight size={36} className="toggle-on" />
                  ) : (
                    <ToggleLeft size={36} className="toggle-off" />
                  )}
                </button>
              </div>
              <div className="panel-card-body">
                <h3 className="panel-card-title">{label}</h3>
                <p className="panel-card-desc">{description}</p>
              </div>
              <div className="panel-card-footer">
                <span className={`panel-status ${enabled ? 'status-enabled' : 'status-disabled'}`}>
                  {enabled ? 'Đang hiển thị' : 'Đã ẩn'}
                </span>
              </div>
            </div>
          );
        })}
      </div>
    </div>
  );
};

export default AdminPanels;
