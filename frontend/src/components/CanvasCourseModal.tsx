import React, { useState, useEffect } from 'react';
import { X, Loader2, BookOpen, AlertCircle, CheckCircle } from 'lucide-react';
import { useAuth } from '../context/AuthContext';
import { canvasApi } from '../api/canvas';
import { setSelectedCourse } from '../utils/canvasStorage';
import type { CanvasCourse } from '../types/canvas';

interface CanvasCourseModalProps {
  isOpen: boolean;
  onClose: () => void;
  onCourseSelected: (course: CanvasCourse) => void;
}

const CanvasCourseModal: React.FC<CanvasCourseModalProps> = ({
  isOpen,
  onClose,
  onCourseSelected,
}) => {
  const { isAuthenticated, canvasTokens } = useAuth();
  const [courses, setCourses] = useState<CanvasCourse[]>([]);
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [selectedId, setSelectedId] = useState<number | null>(null);

  useEffect(() => {
    if (isOpen) {
      fetchCourses();
    }
  }, [isOpen]);

  const fetchCourses = async () => {
    const isConfigured = isAuthenticated && canvasTokens.length > 0;
    if (!isConfigured) {
      setError(
        !isAuthenticated
          ? 'Please login first to access Canvas integration.'
          : 'Canvas access token not configured. Please add it in Settings.'
      );
      return;
    }

    setLoading(true);
    setError(null);
    setCourses([]);

    try {
      const response = await canvasApi.fetchCourses();
      
      if (!response.success) {
        setError(response.error || 'Failed to fetch courses');
        return;
      }

      if (response.courses.length === 0) {
        setError('No courses found. Make sure your access token has the correct permissions.');
        return;
      }

      setCourses(response.courses);
    } catch (err) {
      setError('Network error. Please check your connection.');
    } finally {
      setLoading(false);
    }
  };

  const handleSelectCourse = (course: CanvasCourse) => {
    setSelectedId(course.id);
    setSelectedCourse(course.id, course.name);
    onCourseSelected(course);
    onClose();
  };

  if (!isOpen) return null;

  return (
    <div className="modal-overlay" onClick={onClose}>
      <div className="modal-content modal-lg canvas-course-modal" onClick={(e) => e.stopPropagation()}>
        <div className="modal-header">
          <h2>
            <BookOpen size={24} />
            Select Canvas Course
          </h2>
          <button className="btn-icon" onClick={onClose}>
            <X size={20} />
          </button>
        </div>

        <div className="modal-body">
          {loading && (
            <div className="modal-loading">
              <Loader2 className="spin" size={32} />
              <p>Loading courses...</p>
            </div>
          )}

          {error && (
            <div className="modal-error">
              <AlertCircle size={24} />
              <div>
                <p className="error-title">Unable to load courses</p>
                <p className="error-message">{error}</p>
              </div>
              <button className="btn-secondary" onClick={fetchCourses}>
                Retry
              </button>
            </div>
          )}

          {!loading && !error && courses.length > 0 && (
            <div className="course-list">
              {courses.map((course) => (
                <div
                  key={course.id}
                  className={`course-item ${selectedId === course.id ? 'selected' : ''}`}
                  onClick={() => handleSelectCourse(course)}
                >
                  <div className="course-info">
                    <span className="course-name">{course.name}</span>
                    <span className="course-code">{course.course_code}</span>
                  </div>
                  <div className="course-status">
                    {course.workflow_state === 'available' && (
                      <span className="status-badge active">Đang hoạt động</span>
                    )}
                    {selectedId === course.id && (
                      <CheckCircle size={20} className="check-icon" />
                    )}
                  </div>
                </div>
              ))}
            </div>
          )}

          {!loading && !error && courses.length === 0 && (
            <div className="modal-empty">
              <BookOpen size={48} />
              <p>No courses available</p>
            </div>
          )}
        </div>

        <div className="modal-footer">
          <button className="btn-secondary" onClick={onClose}>
            Cancel
          </button>
        </div>
      </div>
    </div>
  );
};

export default CanvasCourseModal;
