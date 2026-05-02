import React, { useState, useCallback } from 'react';
import {
  X,
  Star,
  StarOff,
  Trash2,
  Copy,
  Loader2,
  CheckCircle,
  BookOpen,
  Send,
  Pencil,
  Check,
  Tag,
  AlertCircle,
  ListChecks,
  Gauge,
  Languages,
  Sparkles,
} from 'lucide-react';
import { savedQuizApi } from '../api/savedQuiz';
import type { SavedQuizDetail, SavedQuizUpdateRequest } from '../types/savedQuiz';
import type { QuizBuilderQuestion } from '../types/canvas';
import { useEscapeKey } from '../hooks/useEscapeKey';

// ============================================================================
// Props
// ============================================================================

interface QuizDetailModalProps {
  quiz: SavedQuizDetail | null;
  loading: boolean;
  onClose: () => void;
  onToggleStar: (e: React.MouseEvent, quizId: string) => void;
  onDelete: (quizId: string) => void;
  onDuplicate: (quizId: string) => void;
  onLoadToBuilder?: (quiz: SavedQuizDetail) => void;
  onQuizUpdated?: () => void;
}

// ============================================================================
// Helpers
// ============================================================================

const DIFFICULTY_MAP: Record<string, { label: string; color: string }> = {
  easy: { label: 'Dễ', color: '#22c55e' },
  medium: { label: 'Trung bình', color: '#f59e0b' },
  hard: { label: 'Khó', color: '#ef4444' },
};

const SOURCE_MAP: Record<string, string> = {
  rag_generation: 'RAG Generation',
  canvas_import: 'Canvas Import',
  manual: 'Tạo thủ công',
};

const OPTION_LETTERS = ['A', 'B', 'C', 'D', 'E', 'F', 'G', 'H'];

// ============================================================================
// Component
// ============================================================================

const QuizDetailModal: React.FC<QuizDetailModalProps> = ({
  quiz,
  loading,
  onClose,
  onToggleStar,
  onDelete,
  onDuplicate,
  onLoadToBuilder,
  onQuizUpdated,
}) => {
  // Close on Esc whenever the modal is mounted (parent only mounts when open).
  useEscapeKey(onClose, true);
  // ---- Edit metadata state ----
  const [editing, setEditing] = useState(false);
  const [editTitle, setEditTitle] = useState('');
  const [editDescription, setEditDescription] = useState('');
  const [editTags, setEditTags] = useState('');
  const [saving, setSaving] = useState(false);

  // ---- Delete confirm ----
  const [confirmDelete, setConfirmDelete] = useState(false);

  // ---- Start editing ----
  const startEditing = useCallback(() => {
    if (!quiz) return;
    setEditTitle(quiz.title);
    setEditDescription(quiz.description || '');
    setEditTags(quiz.tags.join(', '));
    setEditing(true);
  }, [quiz]);

  // ---- Save edits ----
  const saveEdits = useCallback(async () => {
    if (!quiz) return;
    setSaving(true);
    try {
      const data: SavedQuizUpdateRequest = {
        title: editTitle.trim() || quiz.title,
        description: editDescription.trim() || null,
        tags: editTags
          .split(',')
          .map(t => t.trim())
          .filter(Boolean),
      };
      await savedQuizApi.update(quiz.id, data);
      setEditing(false);
      onQuizUpdated?.();
    } catch (err) {
      console.error('Failed to update quiz', err);
    } finally {
      setSaving(false);
    }
  }, [quiz, editTitle, editDescription, editTags, onQuizUpdated]);

  // ---- Confirm & delete ----
  const handleDeleteConfirm = useCallback(() => {
    if (!quiz) return;
    onDelete(quiz.id);
    setConfirmDelete(false);
  }, [quiz, onDelete]);

  return (
    <div className="modal-overlay" onClick={onClose}>
      <div
        className="modal-content sq-detail-modal"
        onClick={e => e.stopPropagation()}
      >
        {/* Header */}
        <div className="modal-header">
          <h2>
            <BookOpen size={22} />
            {loading ? 'Đang tải...' : quiz?.title || 'Chi tiết bộ đề'}
          </h2>
          <button className="modal-close-btn" onClick={onClose} aria-label="Đóng">
            <X size={20} />
          </button>
        </div>

        {/* Body */}
        <div className="modal-body">
          {loading ? (
            <div className="modal-loading">
              <Loader2 className="spin" size={32} />
              <p>Đang tải chi tiết...</p>
            </div>
          ) : !quiz ? (
            <div className="modal-empty">
              <AlertCircle size={32} />
              <p>Không tìm thấy bộ đề</p>
            </div>
          ) : (
            <>
              {/* Meta section */}
              <div className="sq-detail-meta">
                {editing ? (
                  <div className="sq-detail-edit-form">
                    <label className="sq-edit-label">
                      Tiêu đề
                      <input
                        className="sq-edit-input"
                        value={editTitle}
                        onChange={e => setEditTitle(e.target.value)}
                        placeholder="Tên bộ đề"
                      />
                    </label>
                    <label className="sq-edit-label sq-edit-label-full">
                      Mô tả
                      <textarea
                        className="sq-edit-textarea"
                        value={editDescription}
                        onChange={e => setEditDescription(e.target.value)}
                        placeholder="Mô tả (tùy chọn)"
                        rows={2}
                      />
                    </label>
                    <label className="sq-edit-label sq-edit-label-full">
                      Tags (phân cách bằng dấu phẩy)
                      <input
                        className="sq-edit-input"
                        value={editTags}
                        onChange={e => setEditTags(e.target.value)}
                        placeholder="midterm, chapter1, ..."
                      />
                    </label>
                    <div className="sq-edit-actions">
                      <button
                        className="sq-btn sq-btn-primary"
                        onClick={saveEdits}
                        disabled={saving}
                      >
                        {saving ? <Loader2 className="spin" size={14} /> : <Check size={14} />}
                        Lưu
                      </button>
                      <button
                        className="sq-btn sq-btn-secondary"
                        onClick={() => setEditing(false)}
                      >
                        Hủy
                      </button>
                    </div>
                  </div>
                ) : (
                  <>
                    <div className="sq-detail-stats">
                      <div className="sq-stat">
                        <div className="sq-stat-icon"><ListChecks size={18} /></div>
                        <div className="sq-stat-body">
                          <span className="sq-stat-label">Số câu hỏi</span>
                          <span className="sq-stat-value">{quiz.question_count} câu</span>
                        </div>
                      </div>
                      {quiz.difficulty && (
                        <div className="sq-stat">
                          <div
                            className="sq-stat-icon"
                            style={{ color: DIFFICULTY_MAP[quiz.difficulty]?.color }}
                          >
                            <Gauge size={18} />
                          </div>
                          <div className="sq-stat-body">
                            <span className="sq-stat-label">Độ khó</span>
                            <span
                              className="sq-stat-value"
                              style={{ color: DIFFICULTY_MAP[quiz.difficulty]?.color }}
                            >
                              {DIFFICULTY_MAP[quiz.difficulty]?.label || quiz.difficulty}
                            </span>
                          </div>
                        </div>
                      )}
                      {quiz.language && (
                        <div className="sq-stat">
                          <div className="sq-stat-icon"><Languages size={18} /></div>
                          <div className="sq-stat-body">
                            <span className="sq-stat-label">Ngôn ngữ</span>
                            <span className="sq-stat-value">{quiz.language.toUpperCase()}</span>
                          </div>
                        </div>
                      )}
                      <div className="sq-stat">
                        <div className="sq-stat-icon"><Sparkles size={18} /></div>
                        <div className="sq-stat-body">
                          <span className="sq-stat-label">Nguồn</span>
                          <span className="sq-stat-value">{SOURCE_MAP[quiz.source] || quiz.source}</span>
                        </div>
                      </div>
                    </div>
                    {quiz.course_name && (
                      <div className="sq-detail-info-row">
                        <span className="sq-detail-chip">
                          <BookOpen size={13} />
                          {quiz.course_name}
                        </span>
                      </div>
                    )}
                    {quiz.description && (
                      <p className="sq-detail-desc">{quiz.description}</p>
                    )}
                    {quiz.tags.length > 0 && (
                      <div className="sq-detail-tags">
                        <Tag size={13} />
                        {quiz.tags.map(tag => (
                          <span key={tag} className="sq-tag">{tag}</span>
                        ))}
                      </div>
                    )}
                  </>
                )}
              </div>

              {/* Questions */}
              <div className="sq-detail-questions-header">
                <h3 className="sq-detail-questions-title">Danh sách câu hỏi</h3>
              </div>
              <div className="sq-detail-questions">
                {quiz.questions.map((q) => (
                  <div key={q.id} className="sq-question">
                    <div className="sq-question-header">
                      <span className="sq-question-num">
                        <Sparkles size={11} />
                        Câu {q.question_number}
                      </span>
                      <span className="sq-question-points">{q.points} điểm</span>
                    </div>
                    <p className="sq-question-text">{q.question_text}</p>
                    <div className="sq-options">
                      {OPTION_LETTERS.filter(l => q.options[l]).map(letter => {
                        const isCorrect = letter === q.correct_answer;
                        return (
                          <div
                            key={letter}
                            className={`sq-option ${isCorrect ? 'correct' : ''}`}
                          >
                            <span className="sq-option-letter">{letter}</span>
                            <span className="sq-option-text">{q.options[letter]}</span>
                            {isCorrect && <CheckCircle size={15} className="sq-option-check" />}
                          </div>
                        );
                      })}
                    </div>
                    {q.explanation && (
                      <div className="sq-explanation">
                        <span className="sq-explanation-icon">💡</span>
                        <span>{q.explanation}</span>
                      </div>
                    )}
                  </div>
                ))}
              </div>
            </>
          )}
        </div>

        {/* Footer actions */}
        {quiz && !loading && (
          <div className="modal-footer">
            <div className="sq-footer-left">
              {confirmDelete ? (
                <div className="sq-delete-confirm">
                  <span>Xóa bộ đề này?</span>
                  <button className="sq-btn sq-btn-danger" onClick={handleDeleteConfirm}>
                    Xóa
                  </button>
                  <button
                    className="sq-btn sq-btn-secondary"
                    onClick={() => setConfirmDelete(false)}
                  >
                    Hủy
                  </button>
                </div>
              ) : (
                <>
                  <button
                    className="sq-btn sq-btn-icon"
                    onClick={e => onToggleStar(e, quiz.id)}
                    title={quiz.is_starred ? 'Bỏ đánh dấu' : 'Đánh dấu'}
                  >
                    {quiz.is_starred
                      ? <Star size={16} fill="currentColor" className="sq-star-active" />
                      : <StarOff size={16} />
                    }
                  </button>
                  <button
                    className="sq-btn sq-btn-icon"
                    onClick={startEditing}
                    title="Chỉnh sửa"
                  >
                    <Pencil size={16} />
                  </button>
                  <button
                    className="sq-btn sq-btn-icon"
                    onClick={() => onDuplicate(quiz.id)}
                    title="Nhân bản"
                  >
                    <Copy size={16} />
                  </button>
                  <button
                    className="sq-btn sq-btn-icon sq-btn-icon-danger"
                    onClick={() => setConfirmDelete(true)}
                    title="Xóa"
                  >
                    <Trash2 size={16} />
                  </button>
                </>
              )}
            </div>
            <div className="sq-footer-right">
              {onLoadToBuilder && (
                <button
                  className="sq-btn sq-btn-primary"
                  onClick={() => onLoadToBuilder(quiz)}
                >
                  <Send size={14} />
                  Đẩy lên Canvas
                </button>
              )}
            </div>
          </div>
        )}
      </div>
    </div>
  );
};

export default QuizDetailModal;
