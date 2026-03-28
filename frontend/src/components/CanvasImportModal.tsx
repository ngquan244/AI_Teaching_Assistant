import React, { useEffect, useState } from 'react';
import {
  X,
  Upload,
  Loader2,
  CheckCircle,
  AlertCircle,
  ChevronDown,
  BookOpen,
  Server,
  PenSquare,
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

  const getStatusIcon = () => {
    switch (importStatus) {
      case 'creating_migration':
      case 'uploading_to_s3':
      case 'processing':
        return <Loader2 size={48} className="spin" style={{ color: '#3b82f6' }} />;
      case 'completed':
        return <CheckCircle size={48} style={{ color: '#10b981' }} />;
      case 'failed':
        return <AlertCircle size={48} style={{ color: '#ef4444' }} />;
      default:
        return null;
    }
  };

  if (!isOpen) return null;

  return (
    <div className="canvas-import-modal-overlay" onClick={onClose}>
      <div className="canvas-import-modal" onClick={(e) => e.stopPropagation()}>
        <div className="modal-header">
          <h2>
            <Upload size={24} />
            Xuất câu hỏi lên Canvas
          </h2>
          <button className="close-btn" onClick={onClose}>
            <X size={20} />
          </button>
        </div>

        <div className="modal-body">
          {importStatus !== 'idle' && (
            <div className="import-progress-section">
              <div className="progress-icon">{getStatusIcon()}</div>
              <div className="progress-status">
                <span className={`status-badge ${importStatus}`}>
                  {importStatus === 'creating_migration' && 'Đang khởi tạo...'}
                  {importStatus === 'uploading_to_s3' && 'Đang tải lên...'}
                  {importStatus === 'processing' && 'Đang xử lý...'}
                  {importStatus === 'completed' && 'Hoàn tất'}
                  {importStatus === 'failed' && 'Thất bại'}
                </span>
              </div>
              <p className="progress-message">{importMessage}</p>
              {importError && <p className="error-message">{importError}</p>}

              {importStatus === 'completed' && (
                <div style={{ display: 'flex', flexDirection: 'column', gap: '10px', alignItems: 'center' }}>
                  <button className="btn btn-primary" onClick={onClose}>
                    Đóng
                  </button>
                  {onNavigateToQuizBuilder && (
                    <button
                      className="btn btn-secondary"
                      onClick={() => {
                        onClose();
                        onNavigateToQuizBuilder();
                      }}
                      style={{
                        display: 'flex',
                        alignItems: 'center',
                        gap: '8px',
                        background: 'linear-gradient(135deg, rgba(56, 189, 248, 0.15), rgba(139, 92, 246, 0.1))',
                        border: '1px solid rgba(56, 189, 248, 0.3)',
                        color: '#38bdf8',
                      }}
                    >
                      <PenSquare size={16} />
                      Tạo Quiz từ Bank này →
                    </button>
                  )}
                </div>
              )}
              {importStatus === 'failed' && (
                <button className="btn btn-secondary" onClick={() => setImportStatus('idle')}>
                  Thử lại
                </button>
              )}
            </div>
          )}

          {importStatus === 'idle' && (
            <>
              <div className="form-group">
                <label>
                  <Server size={16} />
                  Canvas Connection
                </label>
                <div className="qti-status">
                  {activeToken ? (
                    <>
                      <CheckCircle size={16} style={{ color: '#10b981' }} />
                      <span>{activeToken.canvas_domain}</span>
                    </>
                  ) : (
                    <>
                      <AlertCircle size={16} style={{ color: '#f59e0b' }} />
                      <span>Chưa có Canvas token trong Cài đặt</span>
                    </>
                  )}
                </div>
                {validationErrors.canvas && (
                  <span className="error-text">{validationErrors.canvas}</span>
                )}
                {!isAuthenticated && (
                  <span className="info-text">Vui lòng đăng nhập và thêm Canvas token ở phần Cài đặt</span>
                )}
              </div>

              <div className="form-group">
                <label>
                  <BookOpen size={16} />
                  Khóa học
                </label>
                <div className="course-select-wrapper">
                  <select
                    value={selectedCourseId || ''}
                    onChange={(e) => setSelectedCourseId(Number(e.target.value) || null)}
                    className={validationErrors.course ? 'error' : ''}
                    disabled={courses.length === 0}
                  >
                    <option value="">
                      {courses.length > 0 ? 'Chọn khóa học...' : 'Tải danh sách trước'}
                    </option>
                    {courses.map((course) => (
                      <option key={course.id} value={course.id}>
                        {course.name} ({course.course_code})
                      </option>
                    ))}
                  </select>
                  <button
                    type="button"
                    className="btn btn-sm btn-secondary load-courses-btn"
                    onClick={handleFetchCourses}
                    disabled={isLoadingCourses || !activeToken}
                  >
                    {isLoadingCourses ? (
                      <Loader2 size={14} className="spin" />
                    ) : (
                      <ChevronDown size={14} />
                    )}
                    {isLoadingCourses ? 'Đang tải...' : 'Tải danh sách'}
                  </button>
                </div>
                {coursesError && <span className="error-text">{coursesError}</span>}
                {validationErrors.course && (
                  <span className="error-text">{validationErrors.course}</span>
                )}
              </div>

              <div className="form-group">
                <label>
                  <BookOpen size={16} />
                  Tên ngân hàng câu hỏi
                </label>
                <input
                  type="text"
                  value={questionBankName}
                  onChange={(e) => setQuestionBankName(e.target.value)}
                  placeholder="VD: AI-TA Bank - Chương 1"
                  className={validationErrors.bankName ? 'error' : ''}
                />
                {validationErrors.bankName && (
                  <span className="error-text">{validationErrors.bankName}</span>
                )}
              </div>

              <div className="form-group qti-info">
                <label>Gói QTI</label>
                <div className="qti-status">
                  {qtiZipBlob ? (
                    <>
                      <CheckCircle size={16} style={{ color: '#10b981' }} />
                      <span>Sẵn sàng ({(qtiZipBlob.size / 1024).toFixed(1)} KB)</span>
                    </>
                  ) : (
                    <>
                      <AlertCircle size={16} style={{ color: '#f59e0b' }} />
                      <span>Chưa có gói nào</span>
                    </>
                  )}
                </div>
                {validationErrors.zip && (
                  <span className="error-text">{validationErrors.zip}</span>
                )}
              </div>

              <div className="form-actions">
                <button className="btn btn-secondary" onClick={onClose}>
                  Hủy
                </button>
                <button
                  className="btn btn-primary"
                  onClick={handleImport}
                  disabled={!activeToken || !qtiZipBlob}
                >
                  <Upload size={16} />
                  Import lên Canvas
                </button>
              </div>
            </>
          )}
        </div>
      </div>
    </div>
  );
};

export default CanvasImportModal;
