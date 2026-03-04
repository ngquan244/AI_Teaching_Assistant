import React, { useState, useEffect } from 'react';
import {
  X,
  Upload,
  Loader2,
  CheckCircle,
  AlertCircle,
  ChevronDown,
  Settings,
  BookOpen,
  Server,
  Eye,
  EyeOff,
  PenSquare,
} from 'lucide-react';
import { useAuth } from '../context/AuthContext';
import { authApi } from '../api/auth';
import { fetchCourses, importQTIToCanvas } from '../api/canvas';
import { getCanvasSettings } from '../utils/canvasStorage';
import type { CanvasCourse, ImportProgressStatus } from '../types/canvas';

interface CanvasImportModalProps {
  isOpen: boolean;
  onClose: () => void;
  qtiZipBlob: Blob | null;
  defaultBankName: string;
  /** Optional callback to navigate to Quiz Builder after QTI import */
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
  
  // Form fields
  const [canvasHost, setCanvasHost] = useState('');
  const [accessToken, setAccessToken] = useState('');
  const [showToken, setShowToken] = useState(false);
  const [isFetchingToken, setIsFetchingToken] = useState(false);
  const [selectedCourseId, setSelectedCourseId] = useState<number | null>(null);
  const [questionBankName, setQuestionBankName] = useState(defaultBankName);

  // Courses
  const [courses, setCourses] = useState<CanvasCourse[]>([]);
  const [isLoadingCourses, setIsLoadingCourses] = useState(false);
  const [coursesError, setCoursesError] = useState<string | null>(null);

  // Import progress
  const [importStatus, setImportStatus] = useState<ImportProgressStatus>('idle');
  const [importMessage, setImportMessage] = useState('');
  const [importError, setImportError] = useState<string | null>(null);

  // Validation
  const [validationErrors, setValidationErrors] = useState<Record<string, string>>({});

  // Load saved settings and fetch token on open
  useEffect(() => {
    if (isOpen) {
      // Reset states
      setQuestionBankName(defaultBankName);
      setImportStatus('idle');
      setImportError(null);
      setImportMessage('');
      setShowToken(false);
      
      // Load saved course selection
      const settings = getCanvasSettings();
      if (settings?.selectedCourseId) {
        setSelectedCourseId(settings.selectedCourseId);
      }
      
      // Auto-fetch token from auth context
      const fetchTokenFromAuth = async () => {
        if (isAuthenticated && canvasTokens.length > 0) {
          setIsFetchingToken(true);
          try {
            const result = await authApi.getActiveCanvasToken();
            setAccessToken(result.access_token);
            setCanvasHost(result.canvas_domain);
          } catch (err) {
            console.error('Failed to fetch Canvas token:', err);
            // Keep fields empty if fetch fails
            setAccessToken('');
            setCanvasHost('');
          } finally {
            setIsFetchingToken(false);
          }
        } else {
          // Not authenticated or no token - keep fields empty
          setAccessToken('');
          setCanvasHost('');
        }
      };
      
      fetchTokenFromAuth();
    }
  }, [isOpen, defaultBankName, isAuthenticated, canvasTokens]);

  // Fetch courses when token changes
  const handleFetchCourses = async () => {
    if (!accessToken.trim()) {
      setCoursesError('Access token is required');
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
    } catch (err) {
      setCoursesError('Network error fetching courses');
    } finally {
      setIsLoadingCourses(false);
    }
  };

  // Validate form
  const validateForm = (): boolean => {
    const errors: Record<string, string> = {};

    if (!canvasHost.trim()) {
      errors.canvasHost = 'Canvas URL is required';
    } else if (!canvasHost.startsWith('http')) {
      errors.canvasHost = 'Invalid URL format';
    }

    if (!accessToken.trim()) {
      errors.accessToken = 'Access token is required';
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

  // Convert Blob to Base64
  const blobToBase64 = (blob: Blob): Promise<string> => {
    return new Promise((resolve, reject) => {
      const reader = new FileReader();
      reader.onloadend = () => {
        const base64 = reader.result as string;
        // Remove data URL prefix (e.g., "data:application/zip;base64,")
        const base64Data = base64.split(',')[1] || base64;
        resolve(base64Data);
      };
      reader.onerror = reject;
      reader.readAsDataURL(blob);
    });
  };

  // Handle import
  const handleImport = async () => {
    if (!validateForm() || !qtiZipBlob || !selectedCourseId) return;

    setImportStatus('creating_migration');
    setImportMessage('Creating content migration...');
    setImportError(null);

    try {
      // Convert blob to base64
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

  // Get status icon
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
          {/* Progress State View */}
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

          {/* Form View */}
          {importStatus === 'idle' && (
            <>
              {/* Canvas Host */}
              <div className="form-group">
                <label>
                  <Server size={16} />
                  Canvas URL
                </label>
                <input
                  type="text"
                  value={canvasHost}
                  onChange={(e) => setCanvasHost(e.target.value)}
                  placeholder={isFetchingToken ? 'Đang lấy từ Cài đặt...' : 'https://canvas.example.com'}
                  className={validationErrors.canvasHost ? 'error' : ''}
                  disabled={isFetchingToken}
                />
                {validationErrors.canvasHost && (
                  <span className="error-text">{validationErrors.canvasHost}</span>
                )}
              </div>

              {/* Access Token */}
              <div className="form-group">
                <label>
                  <Settings size={16} />
                  Access Token
                  <span className="label-hint">
                    {isFetchingToken ? '(đang lấy từ Cài đặt...)' : '(từ Cài đặt hoặc nhập thủ công)'}
                  </span>
                </label>
                <div className="token-input-wrapper">
                  <input
                    type={showToken ? 'text' : 'password'}
                    value={accessToken}
                    onChange={(e) => setAccessToken(e.target.value)}
                    placeholder={isFetchingToken ? 'Đang lấy token...' : 'Canvas API access token'}
                    className={validationErrors.accessToken ? 'error' : ''}
                    disabled={isFetchingToken}
                  />
                  <button
                    type="button"
                    className="toggle-visibility"
                    onClick={() => setShowToken(!showToken)}
                    disabled={isFetchingToken}
                  >
                    {isFetchingToken ? (
                      <Loader2 size={14} className="spin" />
                    ) : showToken ? (
                      <EyeOff size={14} />
                    ) : (
                      <Eye size={14} />
                    )}
                  </button>
                </div>
                {validationErrors.accessToken && (
                  <span className="error-text">{validationErrors.accessToken}</span>
                )}
                {!isAuthenticated && (
                  <span className="info-text">Vui lòng đăng nhập và thêm Canvas token ở phần Cài đặt</span>
                )}
              </div>

              {/* Course Selection */}
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
                    disabled={isLoadingCourses || !accessToken.trim()}
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

              {/* Question Bank Name */}
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

              {/* QTI Package Info */}
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
            </>
          )}
        </div>

        {/* Footer */}
        {importStatus === 'idle' && (
          <div className="modal-footer">
            <button className="btn btn-secondary" onClick={onClose}>
              Hủy
            </button>
            <button
              className="btn btn-primary"
              onClick={handleImport}
              disabled={!qtiZipBlob}
            >
              <Upload size={16} />
              Tải QTI lên Canvas
            </button>
          </div>
        )}
      </div>

      <style>{`
        .canvas-import-modal-overlay {
          position: fixed;
          top: 0;
          left: 0;
          right: 0;
          bottom: 0;
          background: rgba(0, 0, 0, 0.65);
          display: flex;
          align-items: center;
          justify-content: center;
          z-index: 1000;
          padding: 20px;
          backdrop-filter: blur(4px);
        }

        .canvas-import-modal {
          background: #131525;
          border-radius: 16px;
          width: 100%;
          max-width: 520px;
          max-height: 90vh;
          overflow: hidden;
          display: flex;
          flex-direction: column;
          box-shadow: 0 25px 60px -12px rgba(0, 0, 0, 0.5), 0 0 0 1px rgba(255,255,255,0.06);
          border: 1px solid rgba(255,255,255,0.08);
        }

        .modal-header {
          display: flex;
          align-items: center;
          justify-content: space-between;
          padding: 20px 24px;
          border-bottom: 1px solid rgba(255,255,255,0.08);
          background: linear-gradient(135deg, rgba(56,189,248,0.12), rgba(129,140,248,0.1));
        }

        .modal-header h2 {
          display: flex;
          align-items: center;
          gap: 12px;
          margin: 0;
          font-size: 1.15rem;
          font-weight: 700;
          background: linear-gradient(135deg, #38bdf8 0%, #818cf8 50%, #a78bfa 100%);
          -webkit-background-clip: text;
          -webkit-text-fill-color: transparent;
          background-clip: text;
        }

        .close-btn {
          background: rgba(255, 255, 255, 0.06);
          border: 1px solid rgba(255,255,255,0.1);
          padding: 8px;
          border-radius: 8px;
          cursor: pointer;
          color: #94a3b8;
          transition: all 0.2s;
        }

        .close-btn:hover {
          background: rgba(255, 255, 255, 0.1);
          color: #e2e8f0;
        }

        .modal-body {
          padding: 24px;
          overflow-y: auto;
          flex: 1;
          color: #e2e8f0;
        }

        .form-group {
          margin-bottom: 20px;
        }

        .form-group label {
          display: flex;
          align-items: center;
          gap: 8px;
          font-weight: 600;
          color: #94a3b8;
          margin-bottom: 8px;
          font-size: 0.85rem;
          text-transform: uppercase;
          letter-spacing: 0.03em;
        }

        .label-hint {
          font-weight: 400;
          color: #475569;
          font-size: 0.78rem;
          text-transform: none;
          letter-spacing: 0;
        }

        .form-group input,
        .form-group select {
          width: 100%;
          padding: 11px 14px;
          border: 1px solid rgba(255,255,255,0.1);
          border-radius: 10px;
          font-size: 0.9rem;
          transition: all 0.2s;
          background: rgba(255,255,255,0.04);
          color: #e2e8f0;
        }

        .form-group input::placeholder {
          color: #475569;
        }

        .form-group input:focus,
        .form-group select:focus {
          outline: none;
          border-color: #38bdf8;
          box-shadow: 0 0 0 3px rgba(56,189,248,0.12);
          background: rgba(255,255,255,0.06);
        }

        .form-group input.error,
        .form-group select.error {
          border-color: #ef4444;
        }

        .form-group select option {
          background: #1e293b;
          color: #e2e8f0;
        }

        .error-text {
          display: block;
          color: #f87171;
          font-size: 0.8rem;
          margin-top: 6px;
        }

        .info-text {
          display: block;
          color: #f59e0b;
          font-size: 0.8rem;
          margin-top: 6px;
        }

        .token-input-wrapper {
          display: flex;
          gap: 8px;
        }

        .token-input-wrapper input {
          flex: 1;
        }

        .toggle-visibility {
          padding: 0 14px;
          background: rgba(255,255,255,0.05);
          border: 1px solid rgba(255,255,255,0.1);
          border-radius: 10px;
          font-size: 0.85rem;
          color: #94a3b8;
          cursor: pointer;
          transition: all 0.2s;
        }

        .toggle-visibility:hover {
          background: rgba(255,255,255,0.1);
          color: #e2e8f0;
        }

        .course-select-wrapper {
          display: flex;
          gap: 8px;
        }

        .course-select-wrapper select {
          flex: 1;
        }

        .load-courses-btn {
          display: flex;
          align-items: center;
          gap: 6px;
          white-space: nowrap;
        }

        .qti-info .qti-status {
          display: flex;
          align-items: center;
          gap: 8px;
          padding: 12px 16px;
          background: rgba(255,255,255,0.04);
          border-radius: 10px;
          border: 1px solid rgba(255,255,255,0.08);
          color: #cbd5e1;
        }

        .import-progress-section {
          display: flex;
          flex-direction: column;
          align-items: center;
          justify-content: center;
          padding: 40px 20px;
          text-align: center;
        }

        .progress-icon {
          margin-bottom: 20px;
        }

        .progress-status {
          margin-bottom: 12px;
        }

        .status-badge {
          display: inline-block;
          padding: 6px 16px;
          border-radius: 20px;
          font-size: 0.85rem;
          font-weight: 600;
        }

        .status-badge.creating_migration,
        .status-badge.uploading_to_s3,
        .status-badge.processing {
          background: rgba(59,130,246,0.15);
          color: #60a5fa;
        }

        .status-badge.completed {
          background: rgba(16,185,129,0.15);
          color: #34d399;
        }

        .status-badge.failed {
          background: rgba(239,68,68,0.15);
          color: #f87171;
        }

        .progress-message {
          color: #94a3b8;
          font-size: 0.95rem;
          margin-bottom: 16px;
        }

        .import-progress-section .error-message {
          color: #f87171;
          background: rgba(239,68,68,0.1);
          border: 1px solid rgba(239,68,68,0.2);
          padding: 12px 16px;
          border-radius: 8px;
          margin-bottom: 16px;
          max-width: 100%;
          word-break: break-word;
        }

        .modal-footer {
          display: flex;
          justify-content: flex-end;
          gap: 12px;
          padding: 16px 24px;
          border-top: 1px solid rgba(255,255,255,0.08);
          background: rgba(255,255,255,0.02);
        }

        .btn {
          display: flex;
          align-items: center;
          gap: 8px;
          padding: 10px 20px;
          border: none;
          border-radius: 10px;
          font-size: 0.9rem;
          font-weight: 600;
          cursor: pointer;
          transition: all 0.2s;
        }

        .btn-primary {
          background: linear-gradient(135deg, #3b82f6 0%, #6366f1 100%);
          color: white;
          box-shadow: 0 2px 10px rgba(59,130,246,0.25);
        }

        .btn-primary:hover:not(:disabled) {
          filter: brightness(1.1);
          transform: translateY(-1px);
          box-shadow: 0 4px 16px rgba(59,130,246,0.35);
        }

        .btn-primary:disabled {
          background: rgba(255,255,255,0.08);
          color: #475569;
          cursor: not-allowed;
          box-shadow: none;
        }

        .btn-secondary {
          background: rgba(255,255,255,0.06);
          color: #cbd5e1;
          border: 1px solid rgba(255,255,255,0.1);
        }

        .btn-secondary:hover {
          background: rgba(255,255,255,0.1);
          color: #e2e8f0;
        }

        .btn-sm {
          padding: 8px 14px;
          font-size: 0.85rem;
        }

        .spin {
          animation: spin 1s linear infinite;
        }

        @keyframes spin {
          from { transform: rotate(0deg); }
          to { transform: rotate(360deg); }
        }
      `}</style>
    </div>
  );
};

export default CanvasImportModal;
