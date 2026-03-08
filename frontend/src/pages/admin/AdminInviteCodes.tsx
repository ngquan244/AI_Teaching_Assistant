/**
 * Admin Invite Code Management Page
 * Create, list, toggle, delete invite codes + manage signup mode
 *
 * UI: card-based layout, signup mode banner, usage progress bars,
 *     polished modals & empty state.
 */
import React, { useEffect, useState, useCallback } from 'react';
import {
  Plus,
  Trash2,
  ToggleLeft,
  ToggleRight,
  Copy,
  Eye,
  Loader2,
  AlertCircle,
  Check,
  Ticket,
  Users,
  BarChart3,
  Shield,
  ShieldCheck,
  ShieldOff,
  KeyRound,
  Tag,
  Hash,
  CalendarClock,
  UserPlus,
  Info,
} from 'lucide-react';
import {
  adminApi,
  type InviteCode,
  type InviteCodeCreated,
  type InviteCodeList,
  type InviteCodeUsageList,
  type InviteCodeStats,
  type CreateInviteCodeRequest,
  type SignupSettings,
} from '../../api/admin';
import './Admin.css';

// ─── Constants ─────────────────────────────────────────────────────────────
const SIGNUP_MODES = [
  {
    value: 'open',
    label: 'Mở',
    desc: 'Ai cũng có thể đăng ký tài khoản',
    icon: UserPlus,
    color: '#22c55e',
    bg: 'rgba(34, 197, 94, 0.12)',
  },
  {
    value: 'invite',
    label: 'Mã mời',
    desc: 'Chỉ đăng ký được khi có mã mời hợp lệ',
    icon: KeyRound,
    color: '#f59e0b',
    bg: 'rgba(245, 158, 11, 0.12)',
  },
  {
    value: 'closed',
    label: 'Đóng',
    desc: 'Không cho phép đăng ký mới',
    icon: ShieldOff,
    color: '#ef4444',
    bg: 'rgba(239, 68, 68, 0.12)',
  },
] as const;

const AdminInviteCodes: React.FC = () => {
  // ─── State ──────────────────────────────────────────────────────
  const [codes, setCodes] = useState<InviteCodeList | null>(null);
  const [stats, setStats] = useState<InviteCodeStats | null>(null);
  const [signupSettings, setSignupSettings] = useState<SignupSettings | null>(null);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);
  const [success, setSuccess] = useState<string | null>(null);

  const [page, setPage] = useState(1);
  const [activeOnly, setActiveOnly] = useState(false);

  // Create modal
  const [showCreate, setShowCreate] = useState(false);
  const [createForm, setCreateForm] = useState<CreateInviteCodeRequest>({});
  const [createdCode, setCreatedCode] = useState<InviteCodeCreated | null>(null);
  const [copied, setCopied] = useState(false);

  // Usages modal
  const [usagesCodeId, setUsagesCodeId] = useState<string | null>(null);
  const [usagesLabel, setUsagesLabel] = useState<string>('');
  const [usages, setUsages] = useState<InviteCodeUsageList | null>(null);
  const [usagesPage, setUsagesPage] = useState(1);
  const [usagesLoading, setUsagesLoading] = useState(false);

  // Delete confirm
  const [deleteCode, setDeleteCode] = useState<InviteCode | null>(null);

  // Action loading
  const [actionLoading, setActionLoading] = useState(false);

  // ─── Fetch ──────────────────────────────────────────────────────
  const fetchAll = useCallback(async () => {
    try {
      setLoading(true);
      setError(null);
      const [codesRes, statsRes, settingsRes] = await Promise.all([
        adminApi.listInviteCodes(page, 20, activeOnly),
        adminApi.getInviteCodeStats(),
        adminApi.getSignupSettings(),
      ]);
      setCodes(codesRes);
      setStats(statsRes);
      setSignupSettings(settingsRes);
    } catch (err: any) {
      setError(err.response?.data?.detail || 'Không thể tải dữ liệu mã mời');
    } finally {
      setLoading(false);
    }
  }, [page, activeOnly]);

  useEffect(() => {
    fetchAll();
  }, [fetchAll]);

  // Auto-dismiss success
  useEffect(() => {
    if (success) {
      const t = setTimeout(() => setSuccess(null), 4000);
      return () => clearTimeout(t);
    }
  }, [success]);

  // ─── Signup mode ────────────────────────────────────────────────
  const handleModeChange = async (mode: string) => {
    if (mode === signupSettings?.mode) return;
    try {
      setActionLoading(true);
      const res = await adminApi.updateSignupSettings({ mode });
      setSignupSettings(res);
      const label = SIGNUP_MODES.find((m) => m.value === mode)?.label || mode;
      setSuccess(`Đã chuyển chế độ đăng ký sang: ${label}`);
    } catch (err: any) {
      setError(err.response?.data?.detail || 'Cập nhật thất bại');
    } finally {
      setActionLoading(false);
    }
  };

  // ─── Create ─────────────────────────────────────────────────────
  const handleCreate = async () => {
    try {
      setActionLoading(true);
      setError(null);
      const data: CreateInviteCodeRequest = {};
      if (createForm.label) data.label = createForm.label;
      if (createForm.max_uses) data.max_uses = createForm.max_uses;
      if (createForm.expires_at) data.expires_at = createForm.expires_at;

      const result = await adminApi.createInviteCode(data);
      setCreatedCode(result);
      setSuccess('Đã tạo mã mời mới');
      fetchAll();
    } catch (err: any) {
      setError(err.response?.data?.detail || 'Tạo mã mời thất bại');
    } finally {
      setActionLoading(false);
    }
  };

  const handleCopy = async (text: string) => {
    try {
      await navigator.clipboard.writeText(text);
      setCopied(true);
      setTimeout(() => setCopied(false), 2000);
    } catch {
      // Fallback
      const ta = document.createElement('textarea');
      ta.value = text;
      document.body.appendChild(ta);
      ta.select();
      document.execCommand('copy');
      document.body.removeChild(ta);
      setCopied(true);
      setTimeout(() => setCopied(false), 2000);
    }
  };

  // ─── Toggle ─────────────────────────────────────────────────────
  const handleToggle = async (codeId: string) => {
    try {
      setActionLoading(true);
      await adminApi.toggleInviteCode(codeId);
      setSuccess('Đã cập nhật trạng thái mã mời');
      fetchAll();
    } catch (err: any) {
      setError(err.response?.data?.detail || 'Thao tác thất bại');
    } finally {
      setActionLoading(false);
    }
  };

  // ─── Delete ─────────────────────────────────────────────────────
  const handleDelete = async () => {
    if (!deleteCode) return;
    try {
      setActionLoading(true);
      await adminApi.deleteInviteCode(deleteCode.id);
      setSuccess('Đã xoá mã mời');
      setDeleteCode(null);
      fetchAll();
    } catch (err: any) {
      setError(err.response?.data?.detail || 'Xoá thất bại');
    } finally {
      setActionLoading(false);
    }
  };

  // ─── Usages ─────────────────────────────────────────────────────
  const openUsages = async (code: InviteCode) => {
    try {
      setUsagesLoading(true);
      setUsagesCodeId(code.id);
      setUsagesLabel(code.label || `${code.code_prefix}…`);
      setUsagesPage(1);
      const res = await adminApi.getInviteCodeUsages(code.id, 1, 20);
      setUsages(res);
    } catch (err: any) {
      setError(err.response?.data?.detail || 'Không thể tải lịch sử sử dụng');
    } finally {
      setUsagesLoading(false);
    }
  };

  const fetchUsagesPage = async (p: number) => {
    if (!usagesCodeId) return;
    try {
      setUsagesLoading(true);
      setUsagesPage(p);
      const res = await adminApi.getInviteCodeUsages(usagesCodeId, p, 20);
      setUsages(res);
    } catch (err: any) {
      setError(err.response?.data?.detail || 'Không thể tải trang');
    } finally {
      setUsagesLoading(false);
    }
  };

  const closeUsages = () => {
    setUsagesCodeId(null);
    setUsages(null);
    setUsagesLabel('');
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

  const getRelativeTime = (d: string) => {
    const diff = new Date(d).getTime() - Date.now();
    if (diff < 0) return 'Đã hết hạn';
    const hours = Math.floor(diff / 3600000);
    if (hours < 24) return `${hours}h nữa`;
    const days = Math.floor(hours / 24);
    return `${days} ngày nữa`;
  };

  const getUsagePercent = (code: InviteCode) => {
    if (!code.max_uses) return null;
    return Math.min(100, Math.round((code.used_count / code.max_uses) * 100));
  };

  // ─── Render ─────────────────────────────────────────────────────
  return (
    <div className="admin-dashboard">
      <h1 className="admin-page-title">Quản lý Mã mời</h1>
      <p className="admin-page-subtitle">
        Tạo, quản lý mã mời đăng ký và điều chỉnh chế độ đăng ký hệ thống
      </p>

      {/* ── Toast messages ───────────────────────────────────────── */}
      {error && (
        <div className="admin-error">
          <AlertCircle size={16} /> {error}
          <button
            className="ic-toast-close"
            onClick={() => setError(null)}
            aria-label="Đóng"
          >×</button>
        </div>
      )}
      {success && (
        <div className="admin-success">
          <Check size={16} /> {success}
        </div>
      )}

      {/* ═══════════════════════════════════════════════════════════
          Signup Mode Banner
          ═══════════════════════════════════════════════════════════ */}
      <div className="ic-mode-banner">
        <div className="ic-mode-banner-header">
          <div className="ic-mode-banner-icon">
            <Shield size={20} />
          </div>
          <div>
            <h3 className="ic-mode-banner-title">Chế độ đăng ký</h3>
            <p className="ic-mode-banner-desc">Chọn cách người dùng mới có thể tạo tài khoản</p>
          </div>
        </div>
        <div className="ic-mode-options">
          {SIGNUP_MODES.map((mode) => {
            const Icon = mode.icon;
            const isActive = signupSettings?.mode === mode.value;
            return (
              <button
                key={mode.value}
                className={`ic-mode-option ${isActive ? 'active' : ''}`}
                onClick={() => handleModeChange(mode.value)}
                disabled={actionLoading}
                style={{
                  '--mode-color': mode.color,
                  '--mode-bg': mode.bg,
                } as React.CSSProperties}
              >
                <div className="ic-mode-option-icon">
                  <Icon size={18} />
                </div>
                <div className="ic-mode-option-text">
                  <span className="ic-mode-option-label">{mode.label}</span>
                  <span className="ic-mode-option-desc">{mode.desc}</span>
                </div>
                {isActive && (
                  <div className="ic-mode-option-check">
                    <Check size={14} />
                  </div>
                )}
              </button>
            );
          })}
        </div>
      </div>

      {/* ═══════════════════════════════════════════════════════════
          Stats Cards
          ═══════════════════════════════════════════════════════════ */}
      {stats && (
        <div className="ic-stats-row">
          <div className="ic-stat-card">
            <div className="ic-stat-icon amber">
              <Ticket size={20} />
            </div>
            <div className="ic-stat-body">
              <span className="ic-stat-value">{stats.total_codes}</span>
              <span className="ic-stat-label">Tổng mã mời</span>
            </div>
          </div>
          <div className="ic-stat-card">
            <div className="ic-stat-icon green">
              <ShieldCheck size={20} />
            </div>
            <div className="ic-stat-body">
              <span className="ic-stat-value">{stats.active_codes}</span>
              <span className="ic-stat-label">Đang hoạt động</span>
            </div>
          </div>
          <div className="ic-stat-card">
            <div className="ic-stat-icon purple">
              <Users size={20} />
            </div>
            <div className="ic-stat-body">
              <span className="ic-stat-value">{stats.total_usages}</span>
              <span className="ic-stat-label">Lượt sử dụng</span>
            </div>
          </div>
          <div className="ic-stat-card">
            <div className="ic-stat-icon blue">
              <BarChart3 size={20} />
            </div>
            <div className="ic-stat-body">
              <span className="ic-stat-value">
                {stats.total_codes > 0
                  ? Math.round((stats.active_codes / stats.total_codes) * 100)
                  : 0}%
              </span>
              <span className="ic-stat-label">Tỷ lệ hoạt động</span>
            </div>
          </div>
        </div>
      )}

      {/* ═══════════════════════════════════════════════════════════
          Toolbar
          ═══════════════════════════════════════════════════════════ */}
      <div className="ic-toolbar">
        <div className="ic-toolbar-left">
          <label className="ic-filter-toggle">
            <input
              type="checkbox"
              checked={activeOnly}
              onChange={(e) => { setActiveOnly(e.target.checked); setPage(1); }}
            />
            <span className="ic-filter-toggle-slider" />
            <span className="ic-filter-toggle-text">Chỉ hiện đang hoạt động</span>
          </label>
          {codes && (
            <span className="ic-codes-count">
              {codes.total} mã mời
            </span>
          )}
        </div>
        <button
          className="admin-btn admin-btn-primary ic-create-btn"
          onClick={() => { setShowCreate(true); setCreateForm({}); setCreatedCode(null); }}
        >
          <Plus size={16} /> Tạo mã mời
        </button>
      </div>

      {/* ═══════════════════════════════════════════════════════════
          Invite Codes Table
          ═══════════════════════════════════════════════════════════ */}
      {loading ? (
        <div className="admin-loading">
          <Loader2 size={28} className="animate-spin" />
          <span>Đang tải mã mời…</span>
        </div>
      ) : (!codes || codes.items.length === 0) ? (
        <div className="ic-empty-state">
          <div className="ic-empty-icon">
            <Ticket size={40} />
          </div>
          <h3>Chưa có mã mời nào</h3>
          <p>Bấm "Tạo mã mời" để tạo mã mời đầu tiên cho hệ thống</p>
          <button
            className="admin-btn admin-btn-primary"
            onClick={() => { setShowCreate(true); setCreateForm({}); setCreatedCode(null); }}
          >
            <Plus size={16} /> Tạo mã mời
          </button>
        </div>
      ) : (
        <>
          <div className="admin-table-container">
            <table className="admin-table ic-table">
              <thead>
                <tr>
                  <th>Mã (prefix)</th>
                  <th>Nhãn</th>
                  <th>Trạng thái</th>
                  <th>Sử dụng</th>
                  <th>Hết hạn</th>
                  <th>Tạo bởi</th>
                  <th>Ngày tạo</th>
                  <th>Thao tác</th>
                </tr>
              </thead>
              <tbody>
                {codes.items.map((code) => {
                  const usagePct = getUsagePercent(code);
                  const isExpired = code.expires_at && new Date(code.expires_at).getTime() < Date.now();

                  return (
                    <tr key={code.id} className={!code.is_active ? 'ic-row-disabled' : ''}>
                      <td>
                        <div className="ic-code-prefix">
                          <KeyRound size={13} />
                          <code>{code.code_prefix}…</code>
                        </div>
                      </td>
                      <td>
                        {code.label ? (
                          <span className="ic-table-label">{code.label}</span>
                        ) : (
                          <span className="ic-table-muted">—</span>
                        )}
                      </td>
                      <td>
                        {!code.is_active ? (
                          <span className="admin-badge-status disabled">Vô hiệu</span>
                        ) : isExpired ? (
                          <span className="admin-badge-status disabled">Hết hạn</span>
                        ) : code.max_uses && code.used_count >= code.max_uses ? (
                          <span className="admin-badge-status pending">Đã đầy</span>
                        ) : (
                          <span className="admin-badge-status active">Hoạt động</span>
                        )}
                      </td>
                      <td>
                        <div className="ic-table-usage">
                          <button
                            className="ic-usages-link"
                            onClick={() => openUsages(code)}
                            title="Xem lịch sử sử dụng chi tiết"
                          >
                            <Eye size={12} />
                            {code.used_count} / {code.max_uses ?? '∞'}
                          </button>
                          {usagePct !== null && (
                            <div className="ic-usage-bar ic-usage-bar-sm">
                              <div
                                className={`ic-usage-bar-fill ${usagePct >= 100 ? 'full' : usagePct >= 75 ? 'warn' : ''}`}
                                style={{ width: `${usagePct}%` }}
                              />
                            </div>
                          )}
                        </div>
                      </td>
                      <td>
                        {code.expires_at ? (
                          <span className={`ic-table-expiry ${isExpired ? 'expired' : ''}`} title={formatDate(code.expires_at)}>
                            {isExpired ? 'Đã hết hạn' : getRelativeTime(code.expires_at)}
                          </span>
                        ) : (
                          <span className="ic-table-muted">∞</span>
                        )}
                      </td>
                      <td>
                        <span className="ic-table-email" title={code.created_by_email || ''}>
                          {code.created_by_email || '—'}
                        </span>
                      </td>
                      <td>
                        <span className="ic-table-date">{formatDate(code.created_at)}</span>
                      </td>
                      <td>
                        <div className="ic-table-actions">
                          <button
                            className="ic-toggle-btn"
                            title={code.is_active ? 'Vô hiệu hoá' : 'Kích hoạt'}
                            onClick={() => handleToggle(code.id)}
                            disabled={actionLoading}
                          >
                            {code.is_active ? (
                              <ToggleRight size={20} className="toggle-on" />
                            ) : (
                              <ToggleLeft size={20} className="toggle-off" />
                            )}
                          </button>
                          <button
                            className="admin-action-btn danger"
                            title="Xoá mã mời"
                            onClick={() => setDeleteCode(code)}
                            disabled={actionLoading}
                          >
                            <Trash2 size={14} />
                          </button>
                        </div>
                      </td>
                    </tr>
                  );
                })}
              </tbody>
            </table>
          </div>

          {/* Pagination */}
          {codes.pages > 1 && (
            <div className="admin-pagination">
              <button
                className="admin-btn admin-btn-secondary"
                disabled={page <= 1}
                onClick={() => setPage(page - 1)}
              >
                ← Trước
              </button>
              <span className="admin-page-info">
                Trang {codes.page} / {codes.pages}
              </span>
              <button
                className="admin-btn admin-btn-secondary"
                disabled={page >= codes.pages}
                onClick={() => setPage(page + 1)}
              >
                Sau →
              </button>
            </div>
          )}
        </>
      )}

      {/* ═══════════════════════════════════════════════════════════
          Create Modal
          ═══════════════════════════════════════════════════════════ */}
      {showCreate && !createdCode && (
        <div className="admin-modal-overlay" onClick={() => setShowCreate(false)}>
          <div className="admin-modal ic-modal-create" onClick={(e) => e.stopPropagation()}>
            <div className="ic-modal-header">
              <div className="ic-modal-header-icon create">
                <Plus size={20} />
              </div>
              <h2 className="admin-modal-title">Tạo mã mời mới</h2>
              <p className="ic-modal-subtitle">
                Mã sẽ được tạo tự động và chỉ hiển thị <strong>một lần duy nhất</strong>
              </p>
            </div>

            <div className="admin-modal-field">
              <label>
                <Tag size={13} /> Nhãn
                <span className="ic-field-hint">tuỳ chọn</span>
              </label>
              <input
                placeholder="VD: Lớp 10A — Kỳ 2"
                value={createForm.label || ''}
                onChange={(e) => setCreateForm({ ...createForm, label: e.target.value })}
              />
            </div>

            <div className="admin-modal-field">
              <label>
                <Hash size={13} /> Giới hạn sử dụng
                <span className="ic-field-hint">tuỳ chọn</span>
              </label>
              <input
                type="number"
                min={1}
                placeholder="Không giới hạn"
                value={createForm.max_uses || ''}
                onChange={(e) => {
                  const v = e.target.value ? parseInt(e.target.value, 10) : undefined;
                  setCreateForm({ ...createForm, max_uses: v });
                }}
              />
            </div>

            <div className="admin-modal-field">
              <label>
                <CalendarClock size={13} /> Ngày hết hạn
                <span className="ic-field-hint">tuỳ chọn</span>
              </label>
              <input
                type="datetime-local"
                value={createForm.expires_at ? createForm.expires_at.slice(0, 16) : ''}
                onChange={(e) => setCreateForm({
                  ...createForm,
                  expires_at: e.target.value ? new Date(e.target.value).toISOString() : undefined,
                })}
              />
            </div>

            <div className="admin-modal-actions">
              <button className="admin-btn admin-btn-secondary" onClick={() => setShowCreate(false)}>
                Huỷ
              </button>
              <button
                className="admin-btn admin-btn-primary"
                onClick={handleCreate}
                disabled={actionLoading}
              >
                {actionLoading ? <Loader2 size={16} className="animate-spin" /> : <KeyRound size={16} />}
                Tạo mã mời
              </button>
            </div>
          </div>
        </div>
      )}

      {/* ═══════════════════════════════════════════════════════════
          Created Code Display Modal
          ═══════════════════════════════════════════════════════════ */}
      {createdCode && (
        <div className="admin-modal-overlay" onClick={() => { setCreatedCode(null); setShowCreate(false); }}>
          <div className="admin-modal ic-modal-created" onClick={(e) => e.stopPropagation()}>
            <div className="ic-modal-header">
              <div className="ic-modal-header-icon success">
                <Check size={24} />
              </div>
              <h2 className="admin-modal-title">Mã mời đã được tạo!</h2>
            </div>

            <div className="ic-created-code-box">
              <div className="ic-created-code-warn">
                <AlertCircle size={14} />
                <span>Mã này chỉ hiển thị <strong>MỘT LẦN DUY NHẤT</strong>. Hãy sao chép ngay!</span>
              </div>
              <div className="ic-created-code-display">
                <code className="ic-created-code-text">{createdCode.plaintext_code}</code>
                <button
                  className={`ic-copy-btn ${copied ? 'copied' : ''}`}
                  onClick={() => handleCopy(createdCode.plaintext_code)}
                  title="Sao chép mã"
                >
                  {copied ? <Check size={16} /> : <Copy size={16} />}
                  {copied ? 'Đã chép!' : 'Sao chép'}
                </button>
              </div>
            </div>

            <div className="ic-created-meta">
              {createdCode.label && (
                <div className="ic-created-meta-row">
                  <Tag size={14} /> <strong>Nhãn:</strong> {createdCode.label}
                </div>
              )}
              <div className="ic-created-meta-row">
                <Hash size={14} /> <strong>Giới hạn:</strong> {createdCode.max_uses ? `${createdCode.max_uses} lượt` : 'Không giới hạn'}
              </div>
              {createdCode.expires_at && (
                <div className="ic-created-meta-row">
                  <CalendarClock size={14} /> <strong>Hết hạn:</strong> {formatDate(createdCode.expires_at)}
                </div>
              )}
            </div>

            <div className="admin-modal-actions">
              <button
                className="admin-btn admin-btn-primary"
                onClick={() => { setCreatedCode(null); setShowCreate(false); }}
              >
                Đã sao chép, đóng
              </button>
            </div>
          </div>
        </div>
      )}

      {/* ═══════════════════════════════════════════════════════════
          Delete Confirm Modal
          ═══════════════════════════════════════════════════════════ */}
      {deleteCode && (
        <div className="admin-modal-overlay" onClick={() => setDeleteCode(null)}>
          <div className="admin-modal ic-modal-delete" onClick={(e) => e.stopPropagation()}>
            <div className="ic-modal-header">
              <div className="ic-modal-header-icon danger">
                <Trash2 size={20} />
              </div>
              <h2 className="admin-modal-title">Xác nhận xoá mã mời</h2>
            </div>

            <div className="ic-delete-info">
              <div className="ic-delete-code">
                <KeyRound size={14} />
                <code>{deleteCode.code_prefix}…</code>
                {deleteCode.label && <span className="ic-delete-label">{deleteCode.label}</span>}
              </div>
              <p className="ic-delete-warning">
                <Info size={14} />
                Tất cả lịch sử sử dụng ({deleteCode.used_count} lượt) liên quan cũng sẽ bị xoá.
                Thao tác này <strong>không thể hoàn tác</strong>.
              </p>
            </div>

            <div className="admin-modal-actions">
              <button className="admin-btn admin-btn-secondary" onClick={() => setDeleteCode(null)}>
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

      {/* ═══════════════════════════════════════════════════════════
          Usages Modal
          ═══════════════════════════════════════════════════════════ */}
      {usagesCodeId && usages && (
        <div className="admin-modal-overlay" onClick={closeUsages}>
          <div className="admin-modal ic-modal-usages" onClick={(e) => e.stopPropagation()}>
            <div className="ic-modal-header">
              <div className="ic-modal-header-icon info">
                <Eye size={20} />
              </div>
              <h2 className="admin-modal-title">Lịch sử sử dụng</h2>
              <p className="ic-modal-subtitle">
                Mã: <code className="ic-inline-code">{usagesLabel}</code>
                {' · '}{usages.total} lượt sử dụng
              </p>
            </div>

            {usagesLoading ? (
              <div className="ic-usages-loading">
                <Loader2 size={20} className="animate-spin" /> Đang tải…
              </div>
            ) : usages.items.length === 0 ? (
              <div className="ic-usages-empty">
                <Users size={28} />
                <p>Chưa có ai sử dụng mã mời này</p>
              </div>
            ) : (
              <div className="ic-usages-list">
                {usages.items.map((u) => (
                  <div key={u.id} className="ic-usage-item">
                    <div className="ic-usage-item-avatar">
                      {(u.user_name || u.user_email || '?')[0].toUpperCase()}
                    </div>
                    <div className="ic-usage-item-info">
                      <span className="ic-usage-item-name">{u.user_name || '—'}</span>
                      <span className="ic-usage-item-email">{u.user_email || '—'}</span>
                    </div>
                    <span className="ic-usage-item-time">{formatDate(u.used_at)}</span>
                  </div>
                ))}
              </div>
            )}

            {usages.pages > 1 && (
              <div className="admin-pagination" style={{ marginTop: '0.75rem', paddingTop: '0.75rem', borderTop: '1px solid var(--border)' }}>
                <button className="admin-btn admin-btn-secondary" disabled={usagesPage <= 1} onClick={() => fetchUsagesPage(usagesPage - 1)}>
                  ←
                </button>
                <span className="admin-page-info">
                  {usages.page} / {usages.pages}
                </span>
                <button className="admin-btn admin-btn-secondary" disabled={usagesPage >= usages.pages} onClick={() => fetchUsagesPage(usagesPage + 1)}>
                  →
                </button>
              </div>
            )}

            <div className="admin-modal-actions">
              <button className="admin-btn admin-btn-secondary" onClick={closeUsages}>
                Đóng
              </button>
            </div>
          </div>
        </div>
      )}
    </div>
  );
};

export default AdminInviteCodes;
