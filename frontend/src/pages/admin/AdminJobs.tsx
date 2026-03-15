/**
 * Admin Job Monitoring Page
 * View and manage all jobs across all users
 */
import React, { useEffect, useState, useCallback } from 'react';
import {
  Activity,
  Loader2,
  AlertCircle,
  RefreshCcw,
} from 'lucide-react';
import { adminApi, type AdminJobList } from '../../api/admin';
import './Admin.css';

/** Friendly job type labels */
const JOB_TYPE_LABELS: Record<string, string> = {
  INGEST_DOCUMENT: 'Ingest Doc',
  BUILD_INDEX: 'Build Index',
  RAG_QUERY: 'RAG Query',
  EXTRACT_TOPICS: 'Extract Topics',
  GENERATE_QUIZ: 'Generate Quiz',
  CANVAS_FILE_DOWNLOAD: 'Canvas Download',
  CANVAS_QTI_IMPORT: 'Import QTI',
  CANVAS_INDEX_FILE: 'Index File',
};

const STATUS_OPTIONS = [
  'QUEUED',
  'STARTED',
  'PROGRESS',
  'SUCCEEDED',
  'FAILED',
  'CANCELED',
  'REVOKED',
];

const AdminJobs: React.FC = () => {
  const [data, setData] = useState<AdminJobList | null>(null);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);

  // Filters
  const [page, setPage] = useState(1);
  const [statusFilter, setStatusFilter] = useState('');
  const [typeFilter, setTypeFilter] = useState('');

  const fetchJobs = useCallback(async () => {
    try {
      setLoading(true);
      setError(null);
      const result = await adminApi.listAllJobs({
        page,
        page_size: 20,
        status: statusFilter || undefined,
        job_type: typeFilter || undefined,
      });
      setData(result);
    } catch (err: any) {
      setError(err.response?.data?.error || 'Failed to load jobs');
    } finally {
      setLoading(false);
    }
  }, [page, statusFilter, typeFilter]);

  useEffect(() => {
    fetchJobs();
  }, [fetchJobs]);

  // Auto-refresh every 10s
  useEffect(() => {
    const interval = setInterval(fetchJobs, 10000);
    return () => clearInterval(interval);
  }, [fetchJobs]);

  const formatDate = (d: string | null) => {
    if (!d) return '—';
    return new Date(d).toLocaleDateString('vi-VN', {
      day: '2-digit',
      month: '2-digit',
      year: 'numeric',
      hour: '2-digit',
      minute: '2-digit',
      second: '2-digit',
    });
  };

  const getProgressClass = (status: string) => {
    if (status === 'SUCCEEDED') return 'complete';
    if (status === 'FAILED') return 'failed';
    return '';
  };

  return (
    <div className="admin-dashboard">
      <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'flex-start' }}>
        <div>
          <h1 className="admin-page-title">Quản lý Jobs</h1>
          <p className="admin-page-subtitle">
            Theo dõi tất cả background jobs của mọi user (auto-refresh 10s)
          </p>
        </div>
        <button
          className="admin-btn admin-btn-secondary"
          onClick={fetchJobs}
          disabled={loading}
          style={{ display: 'flex', alignItems: 'center', gap: 6 }}
        >
          <RefreshCcw size={16} className={loading ? 'spin' : ''} />
          Refresh
        </button>
      </div>

      {error && (
        <div className="admin-error">
          <AlertCircle size={16} /> {error}
        </div>
      )}

      {/* Filters */}
      <div className="admin-table-header">
        <div className="admin-filters">
          <select
            className="admin-filter-select"
            value={statusFilter}
            onChange={(e) => { setStatusFilter(e.target.value); setPage(1); }}
          >
            <option value="">Tất cả Status</option>
            {STATUS_OPTIONS.map((s) => (
              <option key={s} value={s}>{s}</option>
            ))}
          </select>
          <select
            className="admin-filter-select"
            value={typeFilter}
            onChange={(e) => { setTypeFilter(e.target.value); setPage(1); }}
          >
            <option value="">Tất cả Job Type</option>
            {Object.entries(JOB_TYPE_LABELS).map(([key, label]) => (
              <option key={key} value={key}>{label}</option>
            ))}
          </select>
        </div>
        {data && (
          <span style={{ fontSize: '0.82rem', color: 'var(--text-muted)' }}>
            {data.total} jobs
          </span>
        )}
      </div>

      {/* Table */}
      {loading && !data ? (
        <div className="admin-loading">
          <Loader2 className="spin" size={28} />
        </div>
      ) : !data || data.items.length === 0 ? (
        <div className="admin-empty">
          <Activity size={40} style={{ marginBottom: '0.5rem', opacity: 0.4 }} />
          <p>Không có job nào</p>
        </div>
      ) : (
        <>
          <div className="admin-table-wrapper">
            <table className="admin-table">
              <thead>
                <tr>
                  <th>Job Type</th>
                  <th>User</th>
                  <th>Status</th>
                  <th>Progress</th>
                  <th>Step</th>
                  <th>Tạo lúc</th>
                  <th>Hoàn thành</th>
                </tr>
              </thead>
              <tbody>
                {data.items.map((job) => (
                  <tr key={job.id}>
                    <td>
                      <span style={{ fontWeight: 600, fontSize: '0.82rem' }}>
                        {JOB_TYPE_LABELS[job.job_type] || job.job_type}
                      </span>
                    </td>
                    <td>
                      {job.user_email ? (
                        <div>
                          <div style={{ fontSize: '0.82rem' }}>{job.user_name || '—'}</div>
                          <div style={{ fontSize: '0.72rem', color: 'var(--text-muted)' }}>
                            {job.user_email}
                          </div>
                        </div>
                      ) : (
                        <span style={{ color: 'var(--text-muted)', fontSize: '0.82rem' }}>
                          System
                        </span>
                      )}
                    </td>
                    <td>
                      <span className={`admin-badge-status ${job.status.toLowerCase()}`}>
                        {job.status}
                      </span>
                    </td>
                    <td>
                      <div className="admin-progress-bar">
                        <div
                          className={`admin-progress-bar-fill ${getProgressClass(job.status)}`}
                          style={{ width: `${job.progress_pct}%` }}
                        />
                      </div>
                      <span style={{ fontSize: '0.72rem', color: 'var(--text-muted)', marginLeft: 4 }}>
                        {job.progress_pct}%
                      </span>
                    </td>
                    <td style={{ fontSize: '0.8rem', color: 'var(--text-secondary)', maxWidth: 200, overflow: 'hidden', textOverflow: 'ellipsis', whiteSpace: 'nowrap' }}>
                      {job.current_step || job.error_message || '—'}
                    </td>
                    <td style={{ fontSize: '0.78rem', color: 'var(--text-secondary)', whiteSpace: 'nowrap' }}>
                      {formatDate(job.created_at)}
                    </td>
                    <td style={{ fontSize: '0.78rem', color: 'var(--text-secondary)', whiteSpace: 'nowrap' }}>
                      {formatDate(job.finished_at)}
                    </td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>

          {/* Pagination */}
          {data.pages > 1 && (
            <div className="admin-pagination">
              <span>
                Trang {data.page} / {data.pages}
              </span>
              <div className="admin-pagination-btns">
                <button
                  className="admin-pagination-btn"
                  disabled={page <= 1}
                  onClick={() => setPage((p) => p - 1)}
                >
                  Trước
                </button>
                <button
                  className="admin-pagination-btn"
                  disabled={page >= data.pages}
                  onClick={() => setPage((p) => p + 1)}
                >
                  Sau
                </button>
              </div>
            </div>
          )}
        </>
      )}
    </div>
  );
};

export default AdminJobs;
