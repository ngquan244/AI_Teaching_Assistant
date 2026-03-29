import React, { useEffect, useState } from 'react';
import {
  X,
  Upload,
  Loader2,
  CheckCircle,
  AlertCircle,
  RefreshCw,
  BookOpen,
  Server,
  PenSquare,
  Package,
} from 'lucide-react';
import { useAuth } from '../context/AuthContext';
import { fetchCourses, importQTIToCanvas } from '../api/canvas';
import { getCanvasSettings } from '../utils/canvasStorage';
import type { CanvasCourse, ImportProgressStatus } from '../types/canvas';

interface CanvasImportModalProps {
  isOpen: boolean;
  onClose: () => void;
  qtiZipBlob: Blob | null;
  defaultBankName: string;
  onNavigateToQuizBuilder?: () => void;
}

const CanvasImportModal: React.FC<CanvasImportModalProps> = ({
  isOpen,
  onClose,
  qtiZipBlob,
  defaultBankName,
  onNavigateToQuizBuilder,
}) => {
  const { canvasTokens, isAuthenticated } = useAuth();
  const activeToken = canvasTokens[0];

  const [selectedCourseId, setSelectedCourseId] = useState<number | null>(null);
  const [questionBankName, setQuestionBankName] = useState(defaultBankName);

  const [courses, setCourses] = useState<CanvasCourse[]>([]);
  const [isLoadingCourses, setIsLoadingCourses] = useState(false);
  const [coursesError, setCoursesError] = useState<string | null>(null);

  const [importStatus, setImportStatus] = useState<ImportProgressStatus>('idle');
  const [importMessage, setImportMessage] = useState('');
  const [importError, setImportError] = useState<string | null>(null);

  const [validationErrors, setValidationErrors] = useState<Record<string, string>>({});

  useEffect(() => {
    if (!isOpen) return;

    setQuestionBankName(defaultBankName);
    setImportStatus('idle');
    setImportError(null);
    setImportMessage('');
    setCoursesError(null);

    const settings = getCanvasSettings();
    if (settings?.selectedCourseId) {
      setSelectedCourseId(settings.selectedCourseId);
    }
  }, [isOpen, defaultBankName]);

  const handleFetchCourses = async () => {
    if (!activeToken) {
      setCoursesError('Canvas token chưa được cấu hình trong Cài đặt');
      return;
    }

    setIsLoadingCourses(true);
    setCoursesError(null);

    try {
      const response = await fetchCourses();
      if (response.success) {
        setCourses(response.courses);
        if (response.courses.length === 0) {
          setCoursesError('No courses found for this account');
        }
      } else {
        setCoursesError(response.error || 'Failed to fetch courses');
      }
    } catch {
      setCoursesError('Network error fetching courses');
    } finally {
      setIsLoadingCourses(false);
    }
  };

  const validateForm = (): boolean => {
    const errors: Record<string, string> = {};

    if (!activeToken) {
      errors.canvas = 'Canvas token chưa được cấu hình trong Cài đặt';
    }
    if (!selectedCourseId) {
      errors.course = 'Please select a course';
    }
    if (!questionBankName.trim()) {
      errors.bankName = 'Question bank name is required';
    }
    if (!qtiZipBlob) {
      errors.zip = 'No QTI package available';
    }

    setValidationErrors(errors);
    return Object.keys(errors).length === 0;
  };

  const blobToBase64 = (blob: Blob): Promise<string> => {
    return new Promise((resolve, reject) => {
      const reader = new FileReader();
      reader.onloadend = () => {
        const base64 = reader.result as string;
        const base64Data = base64.split(',')[1] || base64;
        resolve(base64Data);
      };
      reader.onerror = reject;
      reader.readAsDataURL(blob);
    });
  };

  const handleImport = async () => {
    if (!validateForm() || !qtiZipBlob || !selectedCourseId) return;

    setImportStatus('creating_migration');
    setImportMessage('Creating content migration...');
    setImportError(null);

    try {
      setImportStatus('uploading_to_s3');
      setImportMessage('Preparing QTI package...');
      const base64Zip = await blobToBase64(qtiZipBlob);

      setImportMessage('Uploading to Canvas...');
      const response = await importQTIToCanvas({
        course_id: selectedCourseId,
        question_bank_name: questionBankName.trim(),
        qti_zip_base64: base64Zip,
        filename: `qti_${questionBankName.replace(/\s+/g, '_')}.zip`,
      });

      if (response.success) {
        setImportStatus('completed');
        setImportMessage(response.message || 'Question bank imported successfully!');
      } else {
        setImportStatus('failed');
        setImportError(response.error || 'Import failed');
      }
    } catch (err) {
      setImportStatus('failed');
      setImportError(err instanceof Error ? err.message : 'Unknown error occurred');
    }
  };

  if (!isOpen) return null;

  const isProcessing = importStatus === 'creating_migration' || importStatus === 'uploading_to_s3' || importStatus === 'processing';

  return (
    <div className="modal-overlay" onClick={onClose}>
      <div className="modal-content cim" onClick={(e) => e.stopPropagation()}>
        {/* Header */}
        <div className="modal-header">
          <h2>
            <Upload size={20} />
            Xuất câu hỏi lên Canvas
          </h2>
          <button className="btn-icon" onClick={onClose}>
            <X size={20} />
          </button>
        </div>

        {/* Body */}
        <div className="modal-body">
          {/* ---- PROGRESS / RESULT STATE ---- */}
          {importStatus !== 'idle' && (
            <div className="cim-progress">
              {isProcessing && <Loader2 size={44} className="spin cim-progress-spinner" />}
              {importStatus === 'completed' && <CheckCircle size={44} className="cim-progress-success" />}
              {importStatus === 'failed' && <AlertCircle size={44} className="cim-progress-error" />}

              <span className="cim-progress-label">
                {isProcessing && 'Đang xử lý...'}
                {importStatus === 'completed' && 'Hoàn tất!'}
                {importStatus === 'failed' && 'Thất bại'}
              </span>

              <p className="cim-progress-msg">{importMessage}</p>
              {importError && <p className="cim-progress-err">{importError}</p>}

              {importStatus === 'completed' && (
                <div className="cim-progress-actions">
                  <button className="btn-primary" onClick={onClose}>Đóng</button>
                  {onNavigateToQuizBuilder && (
                    <button
                      className="btn-secondary"
                      onClick={() => { onClose(); onNavigateToQuizBuilder(); }}
                    >
                      <PenSquare size={16} />
                      Tạo Quiz từ Bank này
                    </button>
                  )}
                </div>
              )}
              {importStatus === 'failed' && (
                <button className="btn-secondary" onClick={() => setImportStatus('idle')}>
                  <RefreshCw size={14} /> Thử lại
                </button>
              )}
            </div>
          )}

          {/* ---- FORM STATE ---- */}
          {importStatus === 'idle' && (
            <div className="cim-form">
              {/* Canvas Connection */}
              <div className="cim-field">
                <label className="cim-label">
                  <Server size={15} /> Canvas Connection
                </label>
                <div className={`cim-info-chip ${activeToken ? 'ok' : 'warn'}`}>
                  {activeToken ? <CheckCircle size={15} /> : <AlertCircle size={15} />}
                  <span>{activeToken ? activeToken.canvas_domain : 'Chưa có Canvas token'}</span>
                </div>
                {validationErrors.canvas && <p className="cim-err">{validationErrors.canvas}</p>}
                {!isAuthenticated && <p className="cim-hint">Vui lòng đăng nhập và thêm Canvas token ở phần Cài đặt</p>}
              </div>

              {/* Course */}
              <div className="cim-field">
                <label className="cim-label">
                  <BookOpen size={15} /> Khóa học
                </label>
                <div className="cim-select-row">
                  <select
                    className={`cim-select ${validationErrors.course ? 'err' : ''}`}
                    value={selectedCourseId || ''}
                    onChange={(e) => setSelectedCourseId(Number(e.target.value) || null)}
                    disabled={courses.length === 0}
                  >
                    <option value="">
                      {courses.length > 0 ? 'Chọn khóa học...' : 'Tải danh sách trước'}
                    </option>
                    {courses.map((c) => (
                      <option key={c.id} value={c.id}>{c.name} ({c.course_code})</option>
                    ))}
                  </select>
                  <button
                    type="button"
                    className="cim-load-btn"
                    onClick={handleFetchCourses}
                    disabled={isLoadingCourses || !activeToken}
                  >
                    {isLoadingCourses
                      ? <><Loader2 size={14} className="spin" /> Đang tải…</>
                      : <><RefreshCw size={14} /> Tải danh sách</>
                    }
                  </button>
                </div>
                {coursesError && <p className="cim-err">{coursesError}</p>}
                {validationErrors.course && <p className="cim-err">{validationErrors.course}</p>}
              </div>

              {/* Bank name */}
              <div className="cim-field">
                <label className="cim-label">
                  <BookOpen size={15} /> Tên ngân hàng câu hỏi
                </label>
                <input
                  type="text"
                  className={`cim-input ${validationErrors.bankName ? 'err' : ''}`}
                  value={questionBankName}
                  onChange={(e) => setQuestionBankName(e.target.value)}
                  placeholder="VD: AI-TA Bank - Chương 1"
                />
                {validationErrors.bankName && <p className="cim-err">{validationErrors.bankName}</p>}
              </div>

              {/* QTI status */}
              <div className="cim-field">
                <label className="cim-label">
                  <Package size={15} /> Gói QTI
                </label>
                <div className={`cim-info-chip ${qtiZipBlob ? 'ok' : 'warn'}`}>
                  {qtiZipBlob ? <CheckCircle size={15} /> : <AlertCircle size={15} />}
                  <span>
                    {qtiZipBlob
                      ? `Sẵn sàng (${(qtiZipBlob.size / 1024).toFixed(1)} KB)`
                      : 'Chưa có gói nào'}
                  </span>
                </div>
                {validationErrors.zip && <p className="cim-err">{validationErrors.zip}</p>}
              </div>
            </div>
          )}
        </div>

        {/* Footer */}
        {importStatus === 'idle' && (
          <div className="modal-footer">
            <button className="btn-secondary" onClick={onClose}>Hủy</button>
            <button
              className="btn-primary"
              onClick={handleImport}
              disabled={!activeToken || !qtiZipBlob}
            >
              <Upload size={16} />
              Import lên Canvas
            </button>
          </div>
        )}
      </div>
    </div>
  );
};

export default CanvasImportModal;
