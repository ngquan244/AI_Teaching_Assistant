import React, { useState, useEffect } from 'react';
import {
  X,
  Loader2,
  BookOpen,
  AlertCircle,
  CheckCircle,
  FolderOpen,
  FileText,
  Download,
  Check,
  ChevronRight,
} from 'lucide-react';
import { canvasApi } from '../api/canvas';
import {
  isCanvasConfigured,
  getSelectedCourse,
  setSelectedCourse,
} from '../utils/canvasStorage';
import type { CanvasCourse, CanvasFile } from '../types/canvas';

interface CanvasFileSelectModalProps {
  isOpen: boolean;
  onClose: () => void;
  onFilesSelected: (files: CanvasFile[]) => void;
  acceptedTypes?: string[]; // e.g., ['application/pdf']
}

type ModalStep = 'course' | 'files';

const CanvasFileSelectModal: React.FC<CanvasFileSelectModalProps> = ({
  isOpen,
  onClose,
  onFilesSelected,
  acceptedTypes = ['application/pdf'],
}) => {
  // Step state
  const [step, setStep] = useState<ModalStep>('course');
  
  // Course state
  const [courses, setCourses] = useState<CanvasCourse[]>([]);
  const [selectedCourse, setSelectedCourseState] = useState<CanvasCourse | null>(null);
  const [loadingCourses, setLoadingCourses] = useState(false);
  const [courseError, setCourseError] = useState<string | null>(null);
  
  // Files state
  const [files, setFiles] = useState<CanvasFile[]>([]);
  const [selectedFiles, setSelectedFiles] = useState<Set<number>>(new Set());
  const [loadingFiles, setLoadingFiles] = useState(false);
  const [fileError, setFileError] = useState<string | null>(null);

  // Load on open
  useEffect(() => {
    if (isOpen) {
      // Check if we have a previously selected course
      const stored = getSelectedCourse();
      if (stored) {
        setSelectedCourseState({ id: stored.id, name: stored.name } as CanvasCourse);
        setStep('files');
        fetchFiles(stored.id);
      } else {
        setStep('course');
        fetchCourses();
      }
    } else {
      // Reset state when closed
      setSelectedFiles(new Set());
      setFileError(null);
      setCourseError(null);
    }
  }, [isOpen]);

  const fetchCourses = async () => {
    if (!isCanvasConfigured()) {
      setCourseError('Canvas chưa được cấu hình. Vui lòng thêm access token trong Cài đặt.');
      return;
    }

    setLoadingCourses(true);
    setCourseError(null);
    setCourses([]);

    try {
      const response = await canvasApi.fetchCourses();
      
      if (!response.success) {
        setCourseError(response.error || 'Không thể tải danh sách khóa học');
        return;
      }

      if (response.courses.length === 0) {
        setCourseError('Không tìm thấy khóa học nào.');
        return;
      }

      setCourses(response.courses);
    } catch (err) {
      setCourseError('Lỗi mạng. Vui lòng kiểm tra kết nối.');
    } finally {
      setLoadingCourses(false);
    }
  };

  const fetchFiles = async (courseId: number) => {
    setLoadingFiles(true);
    setFileError(null);
    setFiles([]);

    try {
      const response = await canvasApi.fetchCourseFiles(courseId);
      
      if (!response.success) {
        setFileError(response.error || 'Không thể tải danh sách file');
        return;
      }

      // Filter by accepted types
      const filteredFiles = response.files.filter(file => 
        acceptedTypes.length === 0 || acceptedTypes.includes(file.content_type)
      );

      if (filteredFiles.length === 0) {
        setFileError('Không có file PDF nào trong khóa học này.');
        return;
      }

      setFiles(filteredFiles);
    } catch (err) {
      setFileError('Lỗi mạng khi tải file.');
    } finally {
      setLoadingFiles(false);
    }
  };

  const handleSelectCourse = (course: CanvasCourse) => {
    setSelectedCourseState(course);
    setSelectedCourse(course.id, course.name);
    setStep('files');
    fetchFiles(course.id);
  };

  const handleBackToCourses = () => {
    setStep('course');
    setSelectedFiles(new Set());
    setFiles([]);
    setFileError(null);
    fetchCourses();
  };

  const toggleFileSelection = (fileId: number) => {
    setSelectedFiles(prev => {
      const newSet = new Set(prev);
      if (newSet.has(fileId)) {
        newSet.delete(fileId);
      } else {
        newSet.add(fileId);
      }
      return newSet;
    });
  };

  const selectAllFiles = () => {
    if (selectedFiles.size === files.length) {
      setSelectedFiles(new Set());
    } else {
      setSelectedFiles(new Set(files.map(f => f.id)));
    }
  };

  const handleConfirmSelection = () => {
    const selected = files.filter(f => selectedFiles.has(f.id));
    onFilesSelected(selected);
    onClose();
  };

  const formatFileSize = (bytes: number): string => {
    if (bytes === 0) return '0 B';
    const k = 1024;
    const sizes = ['B', 'KB', 'MB', 'GB'];
    const i = Math.floor(Math.log(bytes) / Math.log(k));
    return parseFloat((bytes / Math.pow(k, i)).toFixed(1)) + ' ' + sizes[i];
  };

  if (!isOpen) return null;

  const isConfigured = isCanvasConfigured();

  return (
    <div className="modal-overlay" onClick={onClose}>
      <div className="modal-content modal-lg canvas-file-modal" onClick={(e) => e.stopPropagation()}>
        {/* Header */}
        <div className="modal-header">
          <h2>
            <FolderOpen size={24} />
            {step === 'course' ? 'Chọn Khóa học Canvas' : 'Chọn File từ Canvas'}
          </h2>
          <button className="btn-icon" onClick={onClose}>
            <X size={20} />
          </button>
        </div>

        {/* Breadcrumb */}
        {step === 'files' && selectedCourse && (
          <div className="canvas-breadcrumb">
            <button className="breadcrumb-item" onClick={handleBackToCourses}>
              <FolderOpen size={16} />
              Khóa học
            </button>
            <ChevronRight size={16} className="breadcrumb-separator" />
            <span className="breadcrumb-current">
              <BookOpen size={16} />
              {selectedCourse.name}
            </span>
          </div>
        )}

        {/* Body */}
        <div className="modal-body">
          {!isConfigured && (
            <div className="canvas-not-configured-modal">
              <AlertCircle size={48} />
              <h3>Canvas chưa được cấu hình</h3>
              <p>Vui lòng thêm Canvas access token trong trang Cài đặt trước.</p>
            </div>
          )}

          {/* Course Selection Step */}
          {isConfigured && step === 'course' && (
            <>
              {loadingCourses && (
                <div className="modal-loading">
                  <Loader2 className="spin" size={32} />
                  <p>Đang tải danh sách khóa học...</p>
                </div>
              )}

              {courseError && (
                <div className="modal-error">
                  <AlertCircle size={24} />
                  <div>
                    <p className="error-title">Không thể tải khóa học</p>
                    <p className="error-message">{courseError}</p>
                  </div>
                  <button className="btn-secondary btn-sm" onClick={fetchCourses}>
                    Thử lại
                  </button>
                </div>
              )}

              {!loadingCourses && !courseError && courses.length > 0 && (
                <div className="course-list">
                  {courses.map((course) => (
                    <div
                      key={course.id}
                      className="course-item"
                      onClick={() => handleSelectCourse(course)}
                    >
                      <div className="course-info">
                        <span className="course-name">{course.name}</span>
                        <span className="course-code">{course.course_code}</span>
                      </div>
                      <div className="course-status">
                        {course.workflow_state === 'available' && (
                          <span className="status-badge active">Active</span>
                        )}
                        <ChevronRight size={20} className="course-arrow" />
                      </div>
                    </div>
                  ))}
                </div>
              )}
            </>
          )}

          {/* File Selection Step */}
          {isConfigured && step === 'files' && (
            <>
              {loadingFiles && (
                <div className="modal-loading">
                  <Loader2 className="spin" size={32} />
                  <p>Đang tải danh sách file...</p>
                </div>
              )}

              {fileError && (
                <div className="modal-error">
                  <AlertCircle size={24} />
                  <div>
                    <p className="error-title">Không thể tải file</p>
                    <p className="error-message">{fileError}</p>
                  </div>
                  <button className="btn-secondary btn-sm" onClick={() => fetchFiles(selectedCourse!.id)}>
                    Thử lại
                  </button>
                </div>
              )}

              {!loadingFiles && !fileError && files.length > 0 && (
                <>
                  {/* Select All Header */}
                  <div className="file-select-header">
                    <button 
                      className="btn-select-all"
                      onClick={selectAllFiles}
                    >
                      <div className={`checkbox ${selectedFiles.size === files.length ? 'checked' : ''}`}>
                        {selectedFiles.size === files.length && <Check size={14} />}
                      </div>
                      <span>
                        {selectedFiles.size === files.length ? 'Bỏ chọn tất cả' : 'Chọn tất cả'}
                      </span>
                    </button>
                    <span className="file-count">
                      {selectedFiles.size > 0 
                        ? `Đã chọn ${selectedFiles.size}/${files.length} file`
                        : `${files.length} file PDF`
                      }
                    </span>
                  </div>

                  {/* File List */}
                  <div className="canvas-file-list">
                    {files.map((file) => (
                      <div
                        key={file.id}
                        className={`canvas-file-item ${selectedFiles.has(file.id) ? 'selected' : ''}`}
                        onClick={() => toggleFileSelection(file.id)}
                      >
                        <div className={`checkbox ${selectedFiles.has(file.id) ? 'checked' : ''}`}>
                          {selectedFiles.has(file.id) && <Check size={14} />}
                        </div>
                        <div className="canvas-file-icon">
                          <FileText size={20} />
                        </div>
                        <div className="canvas-file-info">
                          <span className="canvas-file-name">{file.display_name}</span>
                          <span className="canvas-file-meta">
                            {formatFileSize(file.size)} • {new Date(file.updated_at).toLocaleDateString('vi-VN')}
                          </span>
                        </div>
                        {selectedFiles.has(file.id) && (
                          <CheckCircle size={20} className="file-selected-icon" />
                        )}
                      </div>
                    ))}
                  </div>
                </>
              )}
            </>
          )}
        </div>

        {/* Footer */}
        <div className="modal-footer">
          {step === 'files' && (
            <button className="btn-secondary" onClick={handleBackToCourses}>
              <FolderOpen size={16} />
              Đổi khóa học
            </button>
          )}
          <div className="footer-spacer"></div>
          <button className="btn-secondary" onClick={onClose}>
            Hủy
          </button>
          {step === 'files' && (
            <button 
              className="btn-primary"
              onClick={handleConfirmSelection}
              disabled={selectedFiles.size === 0}
            >
              <Download size={16} />
              Import {selectedFiles.size > 0 && `(${selectedFiles.size})`}
            </button>
          )}
        </div>
      </div>
    </div>
  );
};

export default CanvasFileSelectModal;
