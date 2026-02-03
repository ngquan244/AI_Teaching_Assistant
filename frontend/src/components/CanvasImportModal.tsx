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
} from 'lucide-react';
import { fetchCourses, importQTIToCanvas } from '../api/canvas';
import { getCanvasSettings, getCanvasBaseUrl, getCanvasToken } from '../utils/canvasStorage';
import type { CanvasCourse, ImportProgressStatus } from '../types/canvas';

interface CanvasImportModalProps {
  isOpen: boolean;
  onClose: () => void;
  qtiZipBlob: Blob | null;
  defaultBankName: string;
}

const CanvasImportModal: React.FC<CanvasImportModalProps> = ({
  isOpen,
  onClose,
  qtiZipBlob,
  defaultBankName,
}) => {
  // Form fields
  const [canvasHost, setCanvasHost] = useState(getCanvasBaseUrl());
  const [accessToken, setAccessToken] = useState(getCanvasToken() || '');
  const [showToken, setShowToken] = useState(false);
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

  // Load saved settings on open
  useEffect(() => {
    if (isOpen) {
      const settings = getCanvasSettings();
      if (settings) {
        setCanvasHost(settings.baseUrl);
        setAccessToken(settings.accessToken);
        if (settings.selectedCourseId) {
          setSelectedCourseId(settings.selectedCourseId);
        }
      }
      setQuestionBankName(defaultBankName);
      setImportStatus('idle');
      setImportError(null);
      setImportMessage('');
    }
  }, [isOpen, defaultBankName]);

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
            Import to Canvas Question Bank
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
                  {importStatus === 'creating_migration' && 'Creating Migration'}
                  {importStatus === 'uploading_to_s3' && 'Uploading'}
                  {importStatus === 'processing' && 'Processing'}
                  {importStatus === 'completed' && 'Completed'}
                  {importStatus === 'failed' && 'Failed'}
                </span>
              </div>
              <p className="progress-message">{importMessage}</p>
              {importError && <p className="error-message">{importError}</p>}
              
              {importStatus === 'completed' && (
                <button className="btn btn-primary" onClick={onClose}>
                  Close
                </button>
              )}
              {importStatus === 'failed' && (
                <button className="btn btn-secondary" onClick={() => setImportStatus('idle')}>
                  Try Again
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
                  placeholder="https://canvas.example.com"
                  className={validationErrors.canvasHost ? 'error' : ''}
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
                  <span className="label-hint">(from Settings or override below)</span>
                </label>
                <div className="token-input-wrapper">
                  <input
                    type={showToken ? 'text' : 'password'}
                    value={accessToken}
                    onChange={(e) => setAccessToken(e.target.value)}
                    placeholder="Canvas API access token"
                    className={validationErrors.accessToken ? 'error' : ''}
                  />
                  <button
                    type="button"
                    className="toggle-visibility"
                    onClick={() => setShowToken(!showToken)}
                  >
                    {showToken ? 'Hide' : 'Show'}
                  </button>
                </div>
                {validationErrors.accessToken && (
                  <span className="error-text">{validationErrors.accessToken}</span>
                )}
              </div>

              {/* Course Selection */}
              <div className="form-group">
                <label>
                  <BookOpen size={16} />
                  Course
                </label>
                <div className="course-select-wrapper">
                  <select
                    value={selectedCourseId || ''}
                    onChange={(e) => setSelectedCourseId(Number(e.target.value) || null)}
                    className={validationErrors.course ? 'error' : ''}
                    disabled={courses.length === 0}
                  >
                    <option value="">
                      {courses.length > 0 ? 'Select a course...' : 'Load courses first'}
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
                    {isLoadingCourses ? 'Loading...' : 'Load Courses'}
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
                  Question Bank Name
                </label>
                <input
                  type="text"
                  value={questionBankName}
                  onChange={(e) => setQuestionBankName(e.target.value)}
                  placeholder="e.g., AI-TA Bank - Chapter 1"
                  className={validationErrors.bankName ? 'error' : ''}
                />
                {validationErrors.bankName && (
                  <span className="error-text">{validationErrors.bankName}</span>
                )}
              </div>

              {/* QTI Package Info */}
              <div className="form-group qti-info">
                <label>QTI Package</label>
                <div className="qti-status">
                  {qtiZipBlob ? (
                    <>
                      <CheckCircle size={16} style={{ color: '#10b981' }} />
                      <span>Ready ({(qtiZipBlob.size / 1024).toFixed(1)} KB)</span>
                    </>
                  ) : (
                    <>
                      <AlertCircle size={16} style={{ color: '#f59e0b' }} />
                      <span>No package available</span>
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
              Cancel
            </button>
            <button
              className="btn btn-primary"
              onClick={handleImport}
              disabled={!qtiZipBlob}
            >
              <Upload size={16} />
              Import to Canvas
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
          background: rgba(0, 0, 0, 0.5);
          display: flex;
          align-items: center;
          justify-content: center;
          z-index: 1000;
          padding: 20px;
        }

        .canvas-import-modal {
          background: white;
          border-radius: 16px;
          width: 100%;
          max-width: 520px;
          max-height: 90vh;
          overflow: hidden;
          display: flex;
          flex-direction: column;
          box-shadow: 0 25px 50px -12px rgba(0, 0, 0, 0.25);
        }

        .modal-header {
          display: flex;
          align-items: center;
          justify-content: space-between;
          padding: 20px 24px;
          border-bottom: 1px solid #e5e7eb;
          background: linear-gradient(135deg, #3b82f6 0%, #1d4ed8 100%);
          color: white;
        }

        .modal-header h2 {
          display: flex;
          align-items: center;
          gap: 12px;
          margin: 0;
          font-size: 1.25rem;
          font-weight: 600;
        }

        .close-btn {
          background: rgba(255, 255, 255, 0.2);
          border: none;
          padding: 8px;
          border-radius: 8px;
          cursor: pointer;
          color: white;
          transition: background 0.2s;
        }

        .close-btn:hover {
          background: rgba(255, 255, 255, 0.3);
        }

        .modal-body {
          padding: 24px;
          overflow-y: auto;
          flex: 1;
        }

        .form-group {
          margin-bottom: 20px;
        }

        .form-group label {
          display: flex;
          align-items: center;
          gap: 8px;
          font-weight: 600;
          color: #374151;
          margin-bottom: 8px;
          font-size: 0.9rem;
        }

        .label-hint {
          font-weight: 400;
          color: #9ca3af;
          font-size: 0.8rem;
        }

        .form-group input,
        .form-group select {
          width: 100%;
          padding: 12px 16px;
          border: 2px solid #e5e7eb;
          border-radius: 10px;
          font-size: 0.95rem;
          transition: all 0.2s;
        }

        .form-group input:focus,
        .form-group select:focus {
          outline: none;
          border-color: #3b82f6;
          box-shadow: 0 0 0 4px rgba(59, 130, 246, 0.1);
        }

        .form-group input.error,
        .form-group select.error {
          border-color: #ef4444;
        }

        .error-text {
          display: block;
          color: #ef4444;
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
          padding: 0 16px;
          background: #f3f4f6;
          border: 2px solid #e5e7eb;
          border-radius: 10px;
          font-size: 0.85rem;
          color: #6b7280;
          cursor: pointer;
          transition: all 0.2s;
        }

        .toggle-visibility:hover {
          background: #e5e7eb;
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
          background: #f9fafb;
          border-radius: 10px;
          border: 1px solid #e5e7eb;
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
          background: #dbeafe;
          color: #1d4ed8;
        }

        .status-badge.completed {
          background: #d1fae5;
          color: #047857;
        }

        .status-badge.failed {
          background: #fee2e2;
          color: #b91c1c;
        }

        .progress-message {
          color: #6b7280;
          font-size: 0.95rem;
          margin-bottom: 16px;
        }

        .import-progress-section .error-message {
          color: #ef4444;
          background: #fef2f2;
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
          border-top: 1px solid #e5e7eb;
          background: #f9fafb;
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
          background: linear-gradient(135deg, #3b82f6 0%, #1d4ed8 100%);
          color: white;
        }

        .btn-primary:hover:not(:disabled) {
          background: linear-gradient(135deg, #2563eb 0%, #1e40af 100%);
          transform: translateY(-1px);
        }

        .btn-primary:disabled {
          background: #94a3b8;
          cursor: not-allowed;
        }

        .btn-secondary {
          background: #f3f4f6;
          color: #374151;
          border: 1px solid #e5e7eb;
        }

        .btn-secondary:hover {
          background: #e5e7eb;
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
