/**
 * Admin Groq Key Pool Management Page
 * List, add, toggle, edit, delete Groq API keys used for quiz generation.
 */
import React, { useEffect, useState, useCallback } from 'react';
import {
  Plus,
  Trash2,
  ToggleLeft,
  ToggleRight,
  Loader2,
  AlertCircle,
  Check,
  Key,
  Edit3,
  ShieldCheck,
  ShieldOff,
  Activity,
  Clock,
  AlertTriangle,
  X,
  Eye,
  EyeOff,
  Info,
} from 'lucide-react';
import {
  adminApi,
  type GroqPoolKey,
  type AddGroqPoolKeyRequest,
  type UpdateGroqPoolKeyRequest,
} from '../../api/admin';
import './Admin.css';

const AdminGroqKeys: React.FC = () => {
  // ─── State ──────────────────────────────────────────────────────
  const [keys, setKeys] = useState<GroqPoolKey[]>([]);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);
  const [success, setSuccess] = useState<string | null>(null);
  const [actionLoading, setActionLoading] = useState(false);

  // Add modal
  const [showAdd, setShowAdd] = useState(false);
  const [addForm, setAddForm] = useState<AddGroqPoolKeyRequest>({ name: '', api_key: '' });

  // Edit modal
  const [editKey, setEditKey] = useState<GroqPoolKey | null>(null);
  const [editForm, setEditForm] = useState<UpdateGroqPoolKeyRequest>({});

  // Delete confirm
  const [deleteTarget, setDeleteTarget] = useState<GroqPoolKey | null>(null);

  // UI helpers
  const [showAddKey, setShowAddKey] = useState(false);
  const [showEditKey, setShowEditKey] = useState(false);

  // ─── Fetch ──────────────────────────────────────────────────────
  const fetchKeys = useCallback(async () => {
    try {
      setLoading(true);
      setError(null);
      const data = await adminApi.listGroqPoolKeys();
      setKeys(data);
    } catch (err: any) {
      setError(err.response?.data?.detail || 'Không thể tải danh sách API keys');
    } finally {
      setLoading(false);
    }
  }, []);

  useEffect(() => {
    fetchKeys();
  }, [fetchKeys]);

  // Auto-dismiss success
  useEffect(() => {
    if (success) {
      const t = setTimeout(() => setSuccess(null), 4000);
      return () => clearTimeout(t);
    }
  }, [success]);

  // ─── Actions ────────────────────────────────────────────────────
  const handleAdd = async () => {
    if (!addForm.name.trim() || !addForm.api_key.trim()) {
      setError('Vui lòng nhập tên và API key');
      return;
    }
    try {
      setActionLoading(true);
      setError(null);
      await adminApi.addGroqPoolKey(addForm);
      setSuccess('Đã thêm API key mới vào pool');
      setShowAdd(false);
      setAddForm({ name: '', api_key: '' });
      fetchKeys();
    } catch (err: any) {
      setError(err.response?.data?.detail || 'Thêm key thất bại');
    } finally {
      setActionLoading(false);
    }
  };

  const handleToggle = async (key: GroqPoolKey) => {
    try {
      setActionLoading(true);
      await adminApi.updateGroqPoolKey(key.id, { enabled: !key.enabled });
      setSuccess(`Đã ${key.enabled ? 'tắt' : 'bật'} key "${key.name}"`);
      fetchKeys();
    } catch (err: any) {
      setError(err.response?.data?.detail || 'Cập nhật thất bại');
    } finally {
      setActionLoading(false);
    }
  };

  const openEdit = (key: GroqPoolKey) => {
    setEditKey(key);
    setEditForm({ name: key.name });
  };

  const handleEdit = async () => {
    if (!editKey) return;
    try {
      setActionLoading(true);
      setError(null);
      await adminApi.updateGroqPoolKey(editKey.id, editForm);
      setSuccess(`Đã cập nhật key "${editForm.name || editKey.name}"`);
      setEditKey(null);
      setEditForm({});
      fetchKeys();
    } catch (err: any) {
      setError(err.response?.data?.detail || 'Cập nhật thất bại');
    } finally {
      setActionLoading(false);
    }
  };

  const handleDelete = async () => {
    if (!deleteTarget) return;
    try {
      setActionLoading(true);
      await adminApi.deleteGroqPoolKey(deleteTarget.id);
      setSuccess(`Đã xoá key "${deleteTarget.name}"`);
      setDeleteTarget(null);
      fetchKeys();
    } catch (err: any) {
      setError(err.response?.data?.detail || 'Xoá thất bại');
    } finally {
      setActionLoading(false);
    }
  };

  // ─── Helpers ────────────────────────────────────────────────────
  const formatDate = (d: string | null) => {
    if (!d) return '—';
    return new Date(d).toLocaleDateString('vi-VN', {
      day: '2-digit',
      month: '2-digit',
      year: 'numeric',
      hour: '2-digit',
      minute: '2-digit',
    });
  };

  const enabledCount = keys.filter((k) => k.enabled).length;
  const errorKeys = keys.filter((k) => k.error_count > 0).length;

  // ─── Render ─────────────────────────────────────────────────────
  return (
    <div className="admin-dashboard">
      <h1 className="admin-page-title">Quản lý Groq API Keys</h1>
      <p className="admin-page-subtitle">
        Quản lý pool API keys cho hệ thống tạo quiz. Các key sẽ được luân chuyển tự động khi tạo bài.
      </p>

      {/* ── Toast ────────────────────────────────────────────────── */}
      {error && (
        <div className="admin-error">
          <AlertCircle size={16} /> {error}
          <button className="ic-toast-close" onClick={() => setError(null)} aria-label="Đóng">×</button>
        </div>
      )}
      {success && (
        <div className="admin-success">
          <Check size={16} /> {success}
        </div>
      )}

      {/* ── Stats Cards ──────────────────────────────────────────── */}
      <div className="ic-stats-row">
        <div className="ic-stat-card">
          <div className="ic-stat-icon amber">
            <Key size={20} />
          </div>
          <div className="ic-stat-body">
            <span className="ic-stat-value">{keys.length}</span>
            <span className="ic-stat-label">Tổng API Keys</span>
          </div>
        </div>
        <div className="ic-stat-card">
          <div className="ic-stat-icon green">
            <ShieldCheck size={20} />
          </div>
          <div className="ic-stat-body">
            <span className="ic-stat-value">{enabledCount}</span>
            <span className="ic-stat-label">Đang bật</span>
          </div>
        </div>
        <div className="ic-stat-card">
          <div className="ic-stat-icon blue">
            <ShieldOff size={20} />
          </div>
          <div className="ic-stat-body">
            <span className="ic-stat-value">{keys.length - enabledCount}</span>
            <span className="ic-stat-label">Đã tắt</span>
          </div>
        </div>
        <div className="ic-stat-card">
          <div className="ic-stat-icon" style={{ background: errorKeys > 0 ? 'rgba(239, 68, 68, 0.12)' : 'rgba(34, 197, 94, 0.12)' }}>
            <AlertTriangle size={20} style={{ color: errorKeys > 0 ? '#ef4444' : '#22c55e' }} />
          </div>
          <div className="ic-stat-body">
            <span className="ic-stat-value">{errorKeys}</span>
            <span className="ic-stat-label">Có lỗi</span>
          </div>
        </div>
      </div>

      {/* ── Toolbar ──────────────────────────────────────────────── */}
      <div className="ic-toolbar">
        <div className="ic-toolbar-left">
          <span className="ic-codes-count">
            {keys.length} keys trong pool
          </span>
        </div>
        <button
          className="admin-btn admin-btn-primary ic-create-btn"
          onClick={() => { setShowAdd(true); setAddForm({ name: '', api_key: '' }); }}
        >
          <Plus size={16} /> Thêm API Key
        </button>
      </div>

      {/* ── Table ────────────────────────────────────────────────── */}
      {loading ? (
        <div className="admin-loading">
          <Loader2 size={28} className="animate-spin" />
          <span>Đang tải…</span>
        </div>
      ) : keys.length === 0 ? (
        <div className="ic-empty-state">
          <div className="ic-empty-icon">
            <Key size={40} />
          </div>
          <h3>Chưa có API key nào</h3>
          <p>Thêm Groq API key để hệ thống có thể tạo quiz. Nhiều key sẽ được luân chuyển tự động.</p>
          <button
            className="admin-btn admin-btn-primary"
            onClick={() => { setShowAdd(true); setAddForm({ name: '', api_key: '' }); }}
          >
            <Plus size={16} /> Thêm API Key
          </button>
        </div>
      ) : (
        <div className="admin-table-container">
          <table className="admin-table ic-table">
            <thead>
              <tr>
                <th>Tên</th>
                <th>API Key</th>
                <th>Trạng thái</th>
                <th>Lỗi</th>
                <th>Sử dụng gần nhất</th>
                <th>Ngày tạo</th>
                <th>Thao tác</th>
              </tr>
            </thead>
            <tbody>
              {keys.map((k) => (
                <tr key={k.id} className={!k.enabled ? 'ic-row-disabled' : ''}>
                  <td>
                    <span style={{ fontWeight: 500 }}>{k.name}</span>
                  </td>
                  <td>
                    <code style={{ fontSize: '0.82rem', color: 'var(--text-secondary)' }}>
                      {k.masked_key}
                    </code>
                  </td>
                  <td>
                    {k.enabled ? (
                      <span className="admin-badge-status active">Bật</span>
                    ) : (
                      <span className="admin-badge-status disabled">Tắt</span>
                    )}
                  </td>
                  <td>
                    {k.error_count > 0 ? (
                      <span
                        className="gk-error-badge"
                        title={k.last_error_at ? `Lỗi gần nhất: ${formatDate(k.last_error_at)}` : ''}
                      >
                        <AlertTriangle size={13} /> {k.error_count}
                      </span>
                    ) : (
                      <span style={{ color: 'var(--text-secondary)' }}>0</span>
                    )}
                  </td>
                  <td style={{ fontSize: '0.85rem', color: 'var(--text-secondary)' }}>
                    {k.last_used_at ? (
                      <span title={formatDate(k.last_used_at)}>
                        <Clock size={12} style={{ marginRight: 4, verticalAlign: -1 }} />
                        {formatDate(k.last_used_at)}
                      </span>
                    ) : '—'}
                  </td>
                  <td style={{ fontSize: '0.85rem', color: 'var(--text-secondary)' }}>
                    {formatDate(k.created_at)}
                  </td>
                  <td>
                    <div className="ic-table-actions">
                      <button
                        className="ic-toggle-btn"
                        title={k.enabled ? 'Tắt key' : 'Bật key'}
                        onClick={() => handleToggle(k)}
                        disabled={actionLoading}
                      >
                        {k.enabled ? <ToggleRight size={20} className="toggle-on" /> : <ToggleLeft size={20} className="toggle-off" />}
                      </button>
                      <button
                        className="admin-action-btn"
                        title="Sửa"
                        onClick={() => openEdit(k)}
                        disabled={actionLoading}
                      >
                        <Edit3 size={14} />
                      </button>
                      <button
                        className="admin-action-btn danger"
                        title="Xoá"
                        onClick={() => setDeleteTarget(k)}
                        disabled={actionLoading}
                      >
                        <Trash2 size={14} />
                      </button>
                    </div>
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      )}

      {/* ═══════════════════════════════════════════════════════════
          Add Key Modal
          ═══════════════════════════════════════════════════════════ */}
      {showAdd && (
        <div className="admin-modal-overlay" onClick={() => setShowAdd(false)}>
          <div className="admin-modal admin-modal-md" onClick={(e) => e.stopPropagation()}>
            <div className="admin-modal-header">
              <div className="admin-modal-title-row">
                <span className="admin-modal-icon admin-modal-icon-primary">
                  <Key size={18} />
                </span>
                <div>
                  <h2>Thêm API Key</h2>
                  <p className="admin-modal-subtitle">Thêm một Groq API key mới vào pool</p>
                </div>
              </div>
              <button
                type="button"
                className="admin-modal-close"
                onClick={() => setShowAdd(false)}
                aria-label="Đóng"
              >
                <X size={18} />
              </button>
            </div>

            <div className="admin-modal-body">
              <div className="admin-modal-hint">
                <Info size={14} />
                <span>API key sẽ được xác thực với Groq trước khi lưu. Key không hợp lệ sẽ bị từ chối.</span>
              </div>

              <div className="admin-form-group">
                <label>Tên hiển thị <span className="admin-required">*</span></label>
                <input
                  type="text"
                  className="admin-input"
                  placeholder="VD: Key chính, Key dự phòng..."
                  value={addForm.name}
                  onChange={(e) => setAddForm({ ...addForm, name: e.target.value })}
                  maxLength={120}
                  autoFocus
                />
              </div>

              <div className="admin-form-group">
                <label>Groq API Key <span className="admin-required">*</span></label>
                <div className="admin-input-wrap">
                  <input
                    type={showAddKey ? 'text' : 'password'}
                    className="admin-input admin-input-with-action"
                    placeholder="gsk_..."
                    value={addForm.api_key}
                    onChange={(e) => setAddForm({ ...addForm, api_key: e.target.value })}
                    maxLength={256}
                    autoComplete="off"
                    spellCheck={false}
                  />
                  <button
                    type="button"
                    className="admin-input-action"
                    onClick={() => setShowAddKey((v) => !v)}
                    aria-label={showAddKey ? 'Hide key' : 'Show key'}
                    tabIndex={-1}
                  >
                    {showAddKey ? <EyeOff size={16} /> : <Eye size={16} />}
                  </button>
                </div>
              </div>
            </div>

            <div className="admin-modal-actions">
              <button
                className="admin-btn admin-btn-secondary"
                onClick={() => setShowAdd(false)}
                disabled={actionLoading}
              >
                Huỷ
              </button>
              <button
                className="admin-btn admin-btn-primary"
                onClick={handleAdd}
                disabled={actionLoading || !addForm.name.trim() || !addForm.api_key.trim()}
              >
                {actionLoading ? <Loader2 size={16} className="animate-spin" /> : <Plus size={16} />}
                Thêm Key
              </button>
            </div>
          </div>
        </div>
      )}

      {/* ═══════════════════════════════════════════════════════════
          Edit Key Modal
          ═══════════════════════════════════════════════════════════ */}
      {editKey && (
        <div className="admin-modal-overlay" onClick={() => setEditKey(null)}>
          <div className="admin-modal admin-modal-md" onClick={(e) => e.stopPropagation()}>
            <div className="admin-modal-header">
              <div className="admin-modal-title-row">
                <span className="admin-modal-icon admin-modal-icon-primary">
                  <Edit3 size={18} />
                </span>
                <div>
                  <h2>Sửa API Key</h2>
                  <p className="admin-modal-subtitle">
                    Key hiện tại: <code className="admin-code">{editKey.masked_key}</code>
                  </p>
                </div>
              </div>
              <button
                type="button"
                className="admin-modal-close"
                onClick={() => setEditKey(null)}
                aria-label="Đóng"
              >
                <X size={18} />
              </button>
            </div>

            <div className="admin-modal-body">
              <div className="admin-form-group">
                <label>Tên hiển thị</label>
                <input
                  type="text"
                  className="admin-input"
                  value={editForm.name ?? ''}
                  onChange={(e) => setEditForm({ ...editForm, name: e.target.value })}
                  maxLength={120}
                />
              </div>

              <div className="admin-form-group">
                <label>
                  API Key mới <span className="admin-label-hint">(để trống nếu không đổi)</span>
                </label>
                <div className="admin-input-wrap">
                  <input
                    type={showEditKey ? 'text' : 'password'}
                    className="admin-input admin-input-with-action"
                    placeholder="gsk_..."
                    value={editForm.api_key ?? ''}
                    onChange={(e) => setEditForm({ ...editForm, api_key: e.target.value || undefined })}
                    maxLength={256}
                    autoComplete="off"
                    spellCheck={false}
                  />
                  <button
                    type="button"
                    className="admin-input-action"
                    onClick={() => setShowEditKey((v) => !v)}
                    aria-label={showEditKey ? 'Hide key' : 'Show key'}
                    tabIndex={-1}
                  >
                    {showEditKey ? <EyeOff size={16} /> : <Eye size={16} />}
                  </button>
                </div>
              </div>
            </div>

            <div className="admin-modal-actions">
              <button
                className="admin-btn admin-btn-secondary"
                onClick={() => setEditKey(null)}
                disabled={actionLoading}
              >
                Huỷ
              </button>
              <button
                className="admin-btn admin-btn-primary"
                onClick={handleEdit}
                disabled={actionLoading}
              >
                {actionLoading ? <Loader2 size={16} className="animate-spin" /> : <Check size={16} />}
                Lưu
              </button>
            </div>
          </div>
        </div>
      )}

      {/* ═══════════════════════════════════════════════════════════
          Delete Confirm Modal
          ═══════════════════════════════════════════════════════════ */}
      {deleteTarget && (
        <div className="admin-modal-overlay" onClick={() => setDeleteTarget(null)}>
          <div className="admin-modal admin-modal-sm admin-modal-danger" onClick={(e) => e.stopPropagation()}>
            <div className="admin-modal-header">
              <div className="admin-modal-title-row">
                <span className="admin-modal-icon admin-modal-icon-danger">
                  <AlertTriangle size={18} />
                </span>
                <div>
                  <h2>Xác nhận xoá</h2>
                  <p className="admin-modal-subtitle">Hành động này không thể hoàn tác</p>
                </div>
              </div>
              <button
                type="button"
                className="admin-modal-close"
                onClick={() => setDeleteTarget(null)}
                aria-label="Đóng"
              >
                <X size={18} />
              </button>
            </div>

            <div className="admin-modal-body">
              <p className="admin-modal-text">
                Bạn có chắc muốn xoá key <strong>“{deleteTarget.name}”</strong>?
              </p>
              <div className="admin-modal-info-box">
                <Key size={14} />
                <code className="admin-code">{deleteTarget.masked_key}</code>
              </div>
              <div className="admin-modal-hint admin-modal-hint-danger">
                <AlertTriangle size={14} />
                <span>Sau khi xoá, key sẽ bị loại khỏi pool ngay lập tức và không thể khôi phục.</span>
              </div>
            </div>

            <div className="admin-modal-actions">
              <button
                className="admin-btn admin-btn-secondary"
                onClick={() => setDeleteTarget(null)}
                disabled={actionLoading}
              >
                Huỷ
              </button>
              <button
                className="admin-btn admin-btn-danger"
                onClick={handleDelete}
                disabled={actionLoading}
              >
                {actionLoading ? <Loader2 size={16} className="animate-spin" /> : <Trash2 size={16} />}
                Xoá vĩnh viễn
              </button>
            </div>
          </div>
        </div>
      )}
    </div>
  );
};

export default AdminGroqKeys;
