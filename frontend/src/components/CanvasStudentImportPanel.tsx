import React, { useCallback, useEffect, useMemo, useRef, useState } from 'react';
import {
  Upload,
  Download,
  Loader2,
  CheckCircle,
  AlertCircle,
  AlertTriangle,
  Users,
  UserPlus,
  RefreshCw,
  FileSpreadsheet,
  Eye,
  Send,
  X,
} from 'lucide-react';
import { canvasApi } from '../api/canvas';
import type { CanvasCourse } from '../types/canvas';
import {
  canvasStudentImportApi,
  type ImportBatch,
  type ImportMode,
  type ImportRow,
  type RowStatus,
} from '../api/canvasStudentImport';

// ============================================================================
// Status → label / tone helpers
// ============================================================================

const STATUS_LABEL: Record<RowStatus, string> = {
  invalid: 'Không hợp lệ',
  duplicate_in_file: 'Trùng trong file',
  skipped: 'Bỏ qua',
  failed: 'Thất bại',
  existed_in_db: 'Đã có trong DB',
  existed_on_canvas: 'Đã có trên Canvas',
  synced_from_canvas: 'Đồng bộ từ Canvas',
  valid_new_user: 'Sẽ tạo mới',
  created: 'Đã tạo',
  old_account_exists: 'Account cũ tồn tại (sẽ tạo sv-email mới)',
  stale_old_account: 'DB có bản ghi cũ (sẽ tạo sv-email mới)',
  user_not_found_on_canvas: 'Không tìm thấy trên Canvas',
  enroll_ready: 'Sẽ enroll',
  already_enrolled: 'Đã enroll',
  enrollment_inactive: 'Enrollment inactive',
  enrollment_completed: 'Enrollment completed',
  enrollment_deleted: 'Enrollment đã xóa',
  enrolled: 'Đã enroll',
  enrollment_failed: 'Enroll thất bại',
};

const STATUS_TONE: Record<RowStatus, 'ok' | 'warn' | 'err' | 'info' | 'muted'> = {
  invalid: 'err',
  duplicate_in_file: 'warn',
  skipped: 'muted',
  failed: 'err',
  existed_in_db: 'info',
  existed_on_canvas: 'info',
  synced_from_canvas: 'info',
  valid_new_user: 'ok',
  created: 'ok',
  old_account_exists: 'warn',
  stale_old_account: 'warn',
  user_not_found_on_canvas: 'err',
  enroll_ready: 'ok',
  already_enrolled: 'info',
  enrollment_inactive: 'warn',
  enrollment_completed: 'muted',
  enrollment_deleted: 'warn',
  enrolled: 'ok',
  enrollment_failed: 'err',
};

function StatusBadge({ status }: { status: RowStatus }) {
  return (
    <span className={`csim-badge tone-${STATUS_TONE[status] || 'info'}`}>
      {STATUS_LABEL[status] || status}
    </span>
  );
}

// ============================================================================
// CSV export
// ============================================================================

function rowsToCsv(rows: ImportRow[]): string {
  const headers = [
    'row_number',
    'student_code',
    'full_name',
    'generated_email',
    'initial_password',
    'status',
    'canvas_user_id',
    'canvas_enrollment_id',
    'sis_user_id_used',
    'error_code',
    'message',
  ];
  const escape = (v: unknown): string => {
    if (v == null) return '';
    const s = String(v);
    if (/[",\n\r]/.test(s)) return `"${s.replace(/"/g, '""')}"`;
    return s;
  };
  const lines = [headers.join(',')];
  for (const r of rows) {
    lines.push(
      [
        r.row_number,
        r.student_code,
        r.full_name,
        r.generated_email,
        r.created_in_this_batch ? r.initial_password : null,
        r.status,
        r.canvas_user_id,
        r.canvas_enrollment_id,
        r.sis_user_id_used,
        r.error_code,
        r.message,
      ]
        .map(escape)
        .join(','),
    );
  }
  return lines.join('\n');
}

function downloadCsv(filename: string, content: string) {
  const blob = new Blob(['\uFEFF', content], { type: 'text/csv;charset=utf-8' });
  const url = URL.createObjectURL(blob);
  const a = document.createElement('a');
  a.href = url;
  a.download = filename;
  document.body.appendChild(a);
  a.click();
  a.remove();
  URL.revokeObjectURL(url);
}

// ============================================================================
// Summary list
// ============================================================================

function Summary({ summary }: { summary: Record<string, number> | null | undefined }) {
  if (!summary) return null;
  const entries = Object.entries(summary).filter(([k]) => k !== '_total');
  const total = summary._total ?? entries.reduce((a, [, v]) => a + v, 0);
  return (
    <div className="csim-summary">
      <span className="csim-summary-total">
        Tổng: <strong>{total}</strong>
      </span>
      {entries.map(([k, v]) => {
        const tone = STATUS_TONE[k as RowStatus] || 'info';
        return (
          <span key={k} className={`csim-badge tone-${tone}`}>
            {STATUS_LABEL[k as RowStatus] || k}: <strong>{v}</strong>
          </span>
        );
      })}
    </div>
  );
}

// ============================================================================
// Main panel
// ============================================================================

const CanvasStudentImportPanel: React.FC = () => {
  // Sub-mode
  const [mode, setMode] = useState<ImportMode>('create');

  // Form
  const [file, setFile] = useState<File | null>(null);
  const fileInputRef = useRef<HTMLInputElement | null>(null);

  const [courses, setCourses] = useState<CanvasCourse[]>([]);
  const [coursesLoading, setCoursesLoading] = useState(false);
  const [courseId, setCourseId] = useState<number | ''>('');
  const [accountId, setAccountId] = useState<number>(1);

  const [enrollAfterCreate, setEnrollAfterCreate] = useState(false);
  const [enrollExisting, setEnrollExisting] = useState(false);
  const [reactivateInactive, setReactivateInactive] = useState(false);
  const [recreateDeleted, setRecreateDeleted] = useState(false);

  // Lifecycle
  const [previewing, setPreviewing] = useState(false);
  const [confirming, setConfirming] = useState(false);
  const [batch, setBatch] = useState<ImportBatch | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [info, setInfo] = useState<string | null>(null);

  // Load courses on mount (used when course_id required)
  const fetchCourses = useCallback(async () => {
    setCoursesLoading(true);
    try {
      const res = await canvasApi.fetchCourses();
      if (res.success) setCourses(res.courses);
    } catch {
      /* ignore */
    } finally {
      setCoursesLoading(false);
    }
  }, []);

  useEffect(() => {
    fetchCourses();
  }, [fetchCourses]);

  // ---- Reset when switching mode ----
  const handleModeChange = (next: ImportMode) => {
    if (next === mode) return;
    if (batch && batch.status === 'preview') {
      const ok = window.confirm(
        'Đổi chế độ sẽ huỷ batch preview hiện tại. Tiếp tục?',
      );
      if (!ok) return;
    }
    setMode(next);
    setBatch(null);
    setError(null);
    setInfo(null);
    if (next === 'create') {
      setEnrollAfterCreate(false);
      setEnrollExisting(false);
    }
  };

  const handleFileChange = (e: React.ChangeEvent<HTMLInputElement>) => {
    const f = e.target.files?.[0] || null;
    setFile(f);
    setError(null);
    setInfo(null);
  };

  const clearFile = () => {
    setFile(null);
    if (fileInputRef.current) fileInputRef.current.value = '';
  };

  // ---- Download template ----
  const handleDownloadTemplate = async () => {
    setError(null);
    const res = await canvasStudentImportApi.downloadTemplate();
    if (!res.success) setError(res.error || 'Không tải được template.');
  };

  // ---- Preview ----
  const handlePreview = async () => {
    if (!file) {
      setError('Vui lòng chọn file .xlsx trước.');
      return;
    }
    if (mode === 'enroll' && !courseId) {
      setError('Mode "Enroll" cần chọn khóa học.');
      return;
    }
    setError(null);
    setInfo(null);
    setPreviewing(true);
    setBatch(null);
    try {
      const res = await canvasStudentImportApi.previewImport({
        file,
        mode,
        account_id: accountId,
        course_id: mode === 'enroll' ? Number(courseId) : (courseId ? Number(courseId) : null),
        enroll_after_create: enrollAfterCreate,
        enroll_existing: enrollExisting,
      });
      if (res.success && res.data) {
        setBatch(res.data);
      } else {
        setError(res.error || 'Preview thất bại.');
      }
    } finally {
      setPreviewing(false);
    }
  };

  // ---- Confirm ----
  const handleConfirm = async () => {
    if (!batch || batch.status !== 'preview') return;
    const ok = window.confirm(
      mode === 'create'
        ? 'Xác nhận tạo các user trên Canvas? Hành động này không thể hoàn tác.'
        : 'Xác nhận enroll các user vào khóa học?',
    );
    if (!ok) return;
    setError(null);
    setInfo(null);
    setConfirming(true);
    try {
      const res = await canvasStudentImportApi.confirmImport({
        batch_id: batch.id,
        enroll_after_create: mode === 'create' ? enrollAfterCreate : undefined,
        enroll_existing: mode === 'create' ? enrollExisting : undefined,
        reactivate_inactive: mode === 'enroll' ? reactivateInactive : false,
        recreate_deleted: mode === 'enroll' ? recreateDeleted : false,
      });
      if (res.success && res.data) {
        setBatch(res.data);
        if (res.already_confirmed) {
          setInfo('Batch này đã được confirm trước đó — đang hiển thị kết quả lần trước.');
        }
      } else {
        setError(res.error || 'Confirm thất bại.');
      }
    } finally {
      setConfirming(false);
    }
  };

  // ---- Refresh batch ----
  const handleRefresh = async () => {
    if (!batch) return;
    const res = await canvasStudentImportApi.getBatch(batch.id);
    if (res.success && res.data) setBatch(res.data);
    else if (res.error) setError(res.error);
  };

  // ---- Reset ----
  const handleReset = () => {
    setBatch(null);
    setError(null);
    setInfo(null);
    clearFile();
  };

  // ---- Export rows ----
  const handleExportCsv = () => {
    if (!batch) return;
    const csv = rowsToCsv(batch.rows);
    const tag = batch.status === 'confirmed' ? 'result' : 'preview';
    downloadCsv(`student_import_${batch.mode}_${tag}_${batch.id.slice(0, 8)}.csv`, csv);
  };

  // ---- Derived ----
  const previewable = !!file && !previewing && !confirming && (mode === 'create' || !!courseId);
  const isPreviewState = batch?.status === 'preview';
  const isConfirmedState = batch?.status === 'confirmed';

  const actionableCount = useMemo(() => {
    if (!batch) return 0;
    if (batch.mode === 'create') {
      return batch.rows.filter(
        (r) =>
          r.status === 'valid_new_user' ||
          r.status === 'old_account_exists' ||
          r.status === 'stale_old_account' ||
          (enrollExisting && (r.status === 'existed_on_canvas' || r.status === 'existed_in_db')),
      ).length;
    }
    return batch.rows.filter((r) => {
      if (r.status === 'enroll_ready') return true;
      if (r.status === 'enrollment_inactive' && reactivateInactive) return true;
      if (r.status === 'enrollment_deleted' && recreateDeleted) return true;
      return false;
    }).length;
  }, [batch, enrollExisting, reactivateInactive, recreateDeleted]);

  // ===== Render =====
  return (
    <>
      <style>{importPanelCss}</style>
      <div className="csim-step-panel">
      {/* Mode switcher */}
      <div className="csim-card">
        <h3 className="csim-card-title">
          <FileSpreadsheet size={18} /> Chế độ
        </h3>
        <div className="csim-mode-switch">
          <button
            className={`csim-mode-btn ${mode === 'create' ? 'active' : ''}`}
            onClick={() => handleModeChange('create')}
          >
            <UserPlus size={16} /> Tạo user từ Excel
          </button>
          <button
            className={`csim-mode-btn ${mode === 'enroll' ? 'active' : ''}`}
            onClick={() => handleModeChange('enroll')}
          >
            <Users size={16} /> Enroll user từ Excel
          </button>
        </div>
        <p className="csim-muted csim-small" style={{ marginTop: 8 }}>
          {mode === 'create'
            ? 'Đọc danh sách MSSV + họ tên, tạo user trên Canvas (email = MSSV@vnu.edu.vn). Có thể enroll thẳng vào khóa học sau khi tạo.'
            : 'Đọc danh sách MSSV, tìm user có sẵn trên Canvas và enroll vào khóa học đã chọn.'}
        </p>
      </div>

      {/* Form */}
      <div className="csim-card">
        <h3 className="csim-card-title">
          <Upload size={18} /> File &amp; tham số
        </h3>

        <div className="csim-row">
          <div className="csim-field" style={{ flex: 2 }}>
            <label className="csim-label">File Excel (.xlsx, ≤ 5 MB)</label>
            <div className="csim-file-row">
              <input
                ref={fileInputRef}
                type="file"
                accept=".xlsx"
                className="csim-input"
                onChange={handleFileChange}
              />
              {file && (
                <button
                  className="csim-btn-icon-sm"
                  onClick={clearFile}
                  title="Bỏ chọn file"
                >
                  <X size={14} />
                </button>
              )}
              <button
                className="csim-btn-secondary"
                onClick={handleDownloadTemplate}
                title="Tải template trống"
              >
                <Download size={14} /> Template
              </button>
            </div>
            {file && (
              <p className="csim-muted csim-small" style={{ marginTop: 4 }}>
                Đã chọn: <strong>{file.name}</strong> ({Math.round(file.size / 1024)} KB)
              </p>
            )}
          </div>

          <div className="csim-field" style={{ maxWidth: 140 }}>
            <label className="csim-label">Account ID</label>
            <input
              type="number"
              className="csim-input"
              value={accountId}
              min={1}
              onChange={(e) => setAccountId(Number(e.target.value) || 1)}
            />
          </div>
        </div>

        {/* Course picker — required for enroll, optional for create */}
        <div className="csim-row" style={{ marginTop: 12 }}>
          <div className="csim-field" style={{ flex: 1 }}>
            <label className="csim-label">
              Khóa học {mode === 'enroll' ? <span className="csim-error-inline">*</span> : '(tuỳ chọn)'}
            </label>
            <div className="csim-file-row">
              <select
                className="csim-input"
                value={courseId}
                onChange={(e) => setCourseId(e.target.value ? Number(e.target.value) : '')}
                disabled={coursesLoading}
              >
                <option value="">— Không chọn —</option>
                {courses.map((c) => (
                  <option key={c.id} value={c.id}>
                    {c.name} (#{c.id})
                  </option>
                ))}
              </select>
              <button
                className="csim-btn-icon-sm"
                onClick={fetchCourses}
                title="Refresh courses"
                disabled={coursesLoading}
              >
                {coursesLoading ? <Loader2 className="spin" size={14} /> : <RefreshCw size={14} />}
              </button>
            </div>
          </div>
        </div>

        {/* Toggles */}
        <div className="csim-row" style={{ marginTop: 12, flexWrap: 'wrap', gap: 12 }}>
          {mode === 'create' && (
            <>
              <label className="csim-checkbox">
                <input
                  type="checkbox"
                  checked={enrollAfterCreate}
                  onChange={(e) => setEnrollAfterCreate(e.target.checked)}
                  disabled={!courseId}
                />
                Enroll user mới vào khóa học sau khi tạo
              </label>
              <label className="csim-checkbox">
                <input
                  type="checkbox"
                  checked={enrollExisting}
                  onChange={(e) => setEnrollExisting(e.target.checked)}
                  disabled={!courseId}
                />
                Enroll cả user đã tồn tại
              </label>
            </>
          )}
          {mode === 'enroll' && (
            <>
              <label className="csim-checkbox">
                <input
                  type="checkbox"
                  checked={reactivateInactive}
                  onChange={(e) => setReactivateInactive(e.target.checked)}
                />
                Reactivate enrollment inactive
              </label>
              <label className="csim-checkbox">
                <input
                  type="checkbox"
                  checked={recreateDeleted}
                  onChange={(e) => setRecreateDeleted(e.target.checked)}
                />
                Recreate enrollment đã xóa
              </label>
            </>
          )}
        </div>

        {/* Action buttons */}
        <div className="csim-row" style={{ marginTop: 16, gap: 12 }}>
          <button
            className="csim-btn-primary"
            disabled={!previewable}
            onClick={handlePreview}
          >
            {previewing ? (
              <>
                <Loader2 className="spin" size={16} /> Đang preview…
              </>
            ) : (
              <>
                <Eye size={16} /> Preview
              </>
            )}
          </button>
          {batch && (
            <button className="csim-btn-secondary" onClick={handleReset} disabled={previewing || confirming}>
              <X size={14} /> Reset
            </button>
          )}
        </div>

        {error && (
          <p className="csim-error" style={{ marginTop: 12 }}>
            <AlertCircle size={14} /> {error}
          </p>
        )}
        {info && (
          <p className="csim-muted" style={{ marginTop: 12 }}>
            <AlertTriangle size={14} /> {info}
          </p>
        )}
      </div>

      {/* Preview / Result */}
      {batch && (
        <div className="csim-card">
          <h3 className="csim-card-title">
            {isConfirmedState ? <CheckCircle size={18} /> : <Eye size={18} />}
            {isConfirmedState ? 'Kết quả' : 'Preview'} ({batch.total_rows} dòng)
            <button
              className="csim-btn-icon-sm"
              onClick={handleRefresh}
              title="Refresh batch"
              style={{ marginLeft: 'auto' }}
              disabled={previewing || confirming}
            >
              <RefreshCw size={14} />
            </button>
            <button
              className="csim-btn-icon-sm"
              onClick={handleExportCsv}
              title="Xuất CSV"
            >
              <Download size={14} />
            </button>
          </h3>

          <Summary summary={batch.summary} />

          {batch.expires_at && isPreviewState && (
            <p className="csim-muted csim-small" style={{ marginTop: 4 }}>
              Preview sẽ hết hạn lúc {new Date(batch.expires_at).toLocaleString('vi-VN')}.
            </p>
          )}

          {isPreviewState && (
            <div style={{ marginTop: 12 }}>
              <button
                className="csim-btn-primary"
                disabled={confirming || actionableCount === 0}
                onClick={handleConfirm}
              >
                {confirming ? (
                  <>
                    <Loader2 className="spin" size={16} /> Đang xử lý…
                  </>
                ) : (
                  <>
                    <Send size={16} />
                    {mode === 'create' ? ` Confirm tạo ${actionableCount} user` : ` Confirm enroll ${actionableCount} user`}
                  </>
                )}
              </button>
              {actionableCount === 0 && (
                <p className="csim-muted csim-small" style={{ marginTop: 6 }}>
                  Không có dòng nào cần xử lý — hãy kiểm tra lại file hoặc bật toggle ở phía trên.
                </p>
              )}
            </div>
          )}

          <div className="csim-table-wrap" style={{ marginTop: 12 }}>
            <table className="csim-table">
              <thead>
                <tr>
                  <th style={{ width: 50 }}>#</th>
                  <th>MSSV</th>
                  <th>Họ tên</th>
                  <th>Email</th>
                  {batch.mode === 'create' &&
                    batch.rows.some((r) => r.created_in_this_batch) && (
                      <th>Mật khẩu</th>
                    )}
                  <th>Trạng thái</th>
                  <th>Canvas UID</th>
                  <th>Enroll ID</th>
                  <th>Ghi chú</th>
                </tr>
              </thead>
              <tbody>
                {batch.rows.map((r) => (
                  <tr key={r.id}>
                    <td className="csim-mono csim-small">{r.row_number}</td>
                    <td className="csim-mono">{r.student_code || '—'}</td>
                    <td>{r.full_name || '—'}</td>
                    <td className="csim-mono csim-small">{r.generated_email || '—'}</td>
                    {batch.mode === 'create' &&
                      batch.rows.some((rr) => rr.created_in_this_batch) && (
                        <td className="csim-mono csim-small">
                          {r.created_in_this_batch ? r.initial_password || '—' : '—'}
                        </td>
                      )}
                    <td>
                      <StatusBadge status={r.status} />
                      {r.status === 'old_account_exists' && (
                        <span
                          className="csim-badge tone-warn"
                          title="Có account cũ theo MSSV/SIS trên Canvas; sẽ tạo account mới dạng svMSSV."
                          style={{ marginLeft: 6 }}
                        >
                          account cũ
                        </span>
                      )}
                    </td>
                    <td className="csim-mono csim-small">{r.canvas_user_id ?? '—'}</td>
                    <td className="csim-mono csim-small">{r.canvas_enrollment_id ?? '—'}</td>
                    <td className="csim-small">
                      {r.error_code && <strong>{r.error_code}</strong>}
                      {r.error_code && r.message && ' — '}
                      {r.message || (r.error_code ? '' : '—')}
                    </td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        </div>
      )}
    </div>
    </>
  );
};

export default CanvasStudentImportPanel;

// ============================================================================
// Embedded CSS — supplements the csim-* styles already injected by
// CanvasSimulationPanel. Defined as a string so the panel works standalone.
// ============================================================================

const importPanelCss = `
.csim-mode-switch { display:flex; gap:8px; flex-wrap:wrap; }
.csim-mode-btn {
  display:inline-flex; align-items:center; gap:6px;
  padding:8px 14px; border-radius:8px;
  background:rgba(255,255,255,0.04);
  border:1px solid rgba(255,255,255,0.08);
  color:#cbd5e1; cursor:pointer;
  font-size:0.85rem; transition: all 0.15s;
}
.csim-mode-btn:hover { background:rgba(255,255,255,0.08); color:#e2e8f0; }
.csim-mode-btn.active {
  background:linear-gradient(135deg,#0ea5e9,#6366f1);
  color:#fff; border-color:transparent;
  box-shadow:0 4px 12px rgba(14,165,233,0.3);
}

.csim-btn-secondary {
  display:inline-flex; align-items:center; gap:6px;
  padding:8px 14px; border-radius:8px;
  background:rgba(255,255,255,0.06);
  border:1px solid rgba(255,255,255,0.1);
  color:#cbd5e1; cursor:pointer;
  font-size:0.85rem; transition: all 0.15s;
}
.csim-btn-secondary:hover:not(:disabled) {
  background:rgba(255,255,255,0.1); color:#e2e8f0;
}
.csim-btn-secondary:disabled { opacity:0.5; cursor:not-allowed; }

.csim-checkbox {
  display:inline-flex; align-items:center; gap:8px;
  color:#cbd5e1; font-size:0.85rem; cursor:pointer;
  user-select:none;
}
.csim-checkbox input[type="checkbox"] { accent-color:#0ea5e9; cursor:pointer; }
.csim-checkbox input[type="checkbox"]:disabled { cursor:not-allowed; }
.csim-checkbox:has(input:disabled) { opacity:0.5; cursor:not-allowed; }

.csim-file-row { display:flex; gap:8px; align-items:center; }
.csim-file-row .csim-input { flex:1; }

.csim-summary {
  display:flex; gap:8px; flex-wrap:wrap; margin-top:8px; align-items:center;
}
.csim-summary-total {
  color:#cbd5e1; font-size:0.85rem; padding:4px 10px;
  background:rgba(255,255,255,0.04); border-radius:6px;
}

.csim-error-inline { color:#f87171; }

/* Tone variants for badges (extend csim-badge) */
.csim-badge.tone-ok    { background:rgba(16,185,129,0.12); color:#34d399; }
.csim-badge.tone-warn  { background:rgba(245,158,11,0.12); color:#fbbf24; }
.csim-badge.tone-err   { background:rgba(239,68,68,0.12);  color:#f87171; }
.csim-badge.tone-info  { background:rgba(59,130,246,0.12); color:#60a5fa; }
.csim-badge.tone-muted { background:rgba(148,163,184,0.12); color:#94a3b8; }
`;
