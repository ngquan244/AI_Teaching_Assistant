/**
 * JobProgressModal — Reusable modal for displaying background job progress.
 *
 * Shows progress bar, current step, cancel button, queued warning, and error state.
 * Uses the existing modal CSS from App.css.
 */
import React from 'react';
import { X, Loader2, AlertTriangle, CheckCircle, XCircle, Ban } from 'lucide-react';
import type { JobOut } from '../api/jobs';
import './JobProgressModal.css';

export interface JobProgressModalProps {
  /** Current job state from useAsyncJob. null = hidden. */
  job: JobOut | null;
  /** Whether to show the modal (controlled by useAsyncJob.showProgress). */
  visible: boolean;
  /** Title displayed in modal header. */
  title: string;
  /** Whether worker-not-running warning should show. */
  queuedWarning?: boolean;
  /** Called when user clicks Cancel. */
  onCancel?: () => void;
  /** Called when user dismisses the modal (after completion/failure). */
  onClose?: () => void;
}

const JobProgressModal: React.FC<JobProgressModalProps> = ({
  job,
  visible,
  title,
  queuedWarning = false,
  onCancel,
  onClose,
}) => {
  if (!visible || !job) return null;

  const isTerminal = ['SUCCEEDED', 'FAILED', 'CANCELED'].includes(job.status);
  const isRunning = job.status === 'RUNNING';
  const isQueued = job.status === 'QUEUED';

  return (
    <div className="modal-overlay" onClick={isTerminal ? onClose : undefined}>
      <div
        className="modal-content job-progress-modal"
        onClick={(e) => e.stopPropagation()}
      >
        {/* Header */}
        <div className="modal-header">
          <h2>
            {job.status === 'SUCCEEDED' && <CheckCircle size={20} />}
            {job.status === 'FAILED' && <XCircle size={20} />}
            {job.status === 'CANCELED' && <Ban size={20} />}
            {(isRunning || isQueued) && (
              <Loader2 size={20} className="spin" />
            )}
            {title}
          </h2>
          {isTerminal && (
            <button className="btn-icon" onClick={onClose}>
              <X size={18} />
            </button>
          )}
        </div>

        {/* Body */}
        <div className="modal-body">
          {/* Progress bar */}
          <div className="job-progress-track">
            <div
              className={`job-progress-fill ${job.status === 'FAILED' ? 'error' : ''} ${job.status === 'SUCCEEDED' ? 'success' : ''}`}
              style={{ width: `${job.progress_pct}%` }}
            />
          </div>

          <div className="job-progress-info">
            <span className="job-progress-step">
              {job.current_step || statusLabel(job.status)}
            </span>
            <span className="job-progress-pct">{job.progress_pct}%</span>
          </div>

          {/* Queued warning */}
          {queuedWarning && isQueued && (
            <div className="job-queued-warning">
              <AlertTriangle size={16} />
              <span>
                Job vẫn đang chờ xử lý. Worker có thể chưa được khởi động.
              </span>
            </div>
          )}

          {/* Error message */}
          {job.status === 'FAILED' && job.error_message && (
            <div className="modal-error" style={{ marginTop: '1rem' }}>
              <XCircle size={20} style={{ flexShrink: 0, marginTop: 2 }} />
              <div>
                <div className="error-title">Lỗi</div>
                <div className="error-message">{job.error_message}</div>
              </div>
            </div>
          )}

          {/* Success message */}
          {job.status === 'SUCCEEDED' && (
            <div className="job-success-msg">
              <CheckCircle size={16} />
              <span>Hoàn thành!</span>
            </div>
          )}
        </div>

        {/* Footer */}
        <div className="modal-footer">
          {isTerminal ? (
            <button className="btn-primary" onClick={onClose}>
              Đóng
            </button>
          ) : (
            <button className="btn-secondary" onClick={onCancel}>
              Hủy
            </button>
          )}
        </div>
      </div>
    </div>
  );
};

function statusLabel(status: string): string {
  switch (status) {
    case 'QUEUED':
      return 'Đang chờ xử lý...';
    case 'RUNNING':
      return 'Đang xử lý...';
    case 'SUCCEEDED':
      return 'Hoàn thành';
    case 'FAILED':
      return 'Thất bại';
    case 'CANCELED':
      return 'Đã hủy';
    default:
      return status;
  }
}

export default JobProgressModal;
