import React, { useState, useEffect, useCallback } from 'react';
import {
  Library,
  Search,
  Star,
  StarOff,
  Loader2,
  BookOpen,
  FolderOpen,
  Tag,
} from 'lucide-react';
import PanelHelpButton from './PanelHelpButton';
import QuizDetailModal from './QuizDetailModal';
import { savedQuizApi } from '../api/savedQuiz';
import { useToast } from '../context/ToastContext';
import type {
  SavedQuiz,
  SavedQuizDetail,
  CourseGroup,
} from '../types/savedQuiz';
import type { QuizBuilderQuestion } from '../types/canvas';
import './SavedQuizzesPanel.css';

// ============================================================================
// Helpers
// ============================================================================

function makeStars(count: number) {
  return Array.from({ length: count }, (_, i) => ({
    id: i,
    top: `${Math.random() * 100}%`,
    left: `${Math.random() * 100}%`,
    size: `${Math.random() * 2 + 1}px`,
    duration: `${Math.random() * 3 + 2}s`,
    delay: `${Math.random() * 3}s`,
  }));
}
const STARS = makeStars(20);

const SOURCE_LABELS: Record<string, { label: string; color: string }> = {
  rag_generation: { label: 'RAG', color: '#818cf8' },
  canvas_import: { label: 'Canvas', color: '#38bdf8' },
  manual: { label: 'Thủ công', color: '#94a3b8' },
};

const DIFFICULTY_LABELS: Record<string, { label: string; color: string }> = {
  easy: { label: 'Dễ', color: '#22c55e' },
  medium: { label: 'Trung bình', color: '#f59e0b' },
  hard: { label: 'Khó', color: '#ef4444' },
};

function timeAgo(dateStr: string): string {
  const now = Date.now();
  const d = new Date(dateStr).getTime();
  const diff = now - d;
  const mins = Math.floor(diff / 60000);
  if (mins < 1) return 'Vừa xong';
  if (mins < 60) return `${mins} phút trước`;
  const hours = Math.floor(mins / 60);
  if (hours < 24) return `${hours} giờ trước`;
  const days = Math.floor(hours / 24);
  if (days < 30) return `${days} ngày trước`;
  const months = Math.floor(days / 30);
  return `${months} tháng trước`;
}

// ============================================================================
// Props
// ============================================================================

export interface SavedQuizzesPanelProps {
  /** Callback to load questions into QuizBuilderPanel for Canvas push */
  onLoadToBuilder?: (questions: QuizBuilderQuestion[]) => void;
}

// ============================================================================
// Component
// ============================================================================

/** Best-effort extraction of a user-friendly message from an axios/fetch error. */
function extractErrorMessage(err: unknown, fallback: string): string {
  const e = err as {
    response?: { data?: { detail?: unknown; message?: unknown } };
    message?: string;
  };
  const detail = e?.response?.data?.detail;
  if (typeof detail === 'string') return detail;
  if (detail && typeof detail === 'object') {
    const d = detail as { message?: unknown; error?: unknown };
    if (typeof d.message === 'string') return d.message;
    if (typeof d.error === 'string') return d.error;
  }
  if (typeof e?.response?.data?.message === 'string') return e.response.data.message as string;
  if (typeof e?.message === 'string') return e.message;
  return fallback;
}

const SavedQuizzesPanel: React.FC<SavedQuizzesPanelProps> = ({ onLoadToBuilder }) => {
  const { showToast } = useToast();

  // ---- Data state ----
  const [quizzes, setQuizzes] = useState<SavedQuiz[]>([]);
  const [courses, setCourses] = useState<CourseGroup[]>([]);
  const [total, setTotal] = useState(0);
  const [loading, setLoading] = useState(false);

  // ---- Filters ----
  const [page, setPage] = useState(1);
  const [pageSize] = useState(12);
  const [selectedCourse, setSelectedCourse] = useState<number | null | 'all'>('all');
  const [searchTerm, setSearchTerm] = useState('');
  const [debouncedSearch, setDebouncedSearch] = useState('');
  const [difficultyFilter, setDifficultyFilter] = useState('');
  const [starredFilter, setStarredFilter] = useState(false);
  const [sortBy, setSortBy] = useState('newest');

  // ---- Detail modal ----
  const [selectedQuizId, setSelectedQuizId] = useState<string | null>(null);
  const [detailQuiz, setDetailQuiz] = useState<SavedQuizDetail | null>(null);
  const [detailLoading, setDetailLoading] = useState(false);

  // ---- Debounce search ----
  useEffect(() => {
    const timer = setTimeout(() => {
      setDebouncedSearch(searchTerm);
      setPage(1);
    }, 300);
    return () => clearTimeout(timer);
  }, [searchTerm]);

  // ---- Fetch quizzes ----
  const fetchQuizzes = useCallback(async () => {
    setLoading(true);
    try {
      const res = await savedQuizApi.list({
        page,
        page_size: pageSize,
        course_id: selectedCourse === 'all' ? undefined : selectedCourse ?? undefined,
        search: debouncedSearch || undefined,
        difficulty: difficultyFilter || undefined,
        starred: starredFilter || undefined,
        sort: sortBy,
      });
      setQuizzes(res.items);
      setTotal(res.total);
      setCourses(res.courses);
    } catch (err) {
      console.error('Failed to fetch saved quizzes', err);
      showToast(extractErrorMessage(err, 'Không thể tải danh sách bộ đề.'), 'error');
    } finally {
      setLoading(false);
    }
  }, [page, pageSize, selectedCourse, debouncedSearch, difficultyFilter, starredFilter, sortBy, showToast]);

  useEffect(() => {
    fetchQuizzes();
  }, [fetchQuizzes]);

  // ---- Detail ----
  const openDetail = useCallback(async (quizId: string) => {
    setSelectedQuizId(quizId);
    setDetailLoading(true);
    try {
      const detail = await savedQuizApi.get(quizId);
      setDetailQuiz(detail);
    } catch (err) {
      console.error('Failed to fetch quiz detail', err);
      showToast(extractErrorMessage(err, 'Không thể mở chi tiết bộ đề.'), 'error');
      setSelectedQuizId(null);
    } finally {
      setDetailLoading(false);
    }
  }, [showToast]);

  const closeDetail = useCallback(() => {
    setSelectedQuizId(null);
    setDetailQuiz(null);
  }, []);

  // ---- Actions ----
  const handleToggleStar = useCallback(async (e: React.MouseEvent, quizId: string) => {
    e.stopPropagation();
    try {
      const updated = await savedQuizApi.toggleStar(quizId);
      setQuizzes(prev => prev.map(q => q.id === quizId ? { ...q, is_starred: updated.is_starred } : q));
      if (detailQuiz?.id === quizId) {
        setDetailQuiz(prev => prev ? { ...prev, is_starred: updated.is_starred } : prev);
      }
      showToast(
        updated.is_starred ? 'Đã đánh dấu bộ đề.' : 'Đã bỏ đánh dấu bộ đề.',
        'success',
        2500,
      );
    } catch (err) {
      console.error('Failed to toggle star', err);
      showToast(extractErrorMessage(err, 'Không thể cập nhật đánh dấu.'), 'error');
    }
  }, [detailQuiz, showToast]);

  const handleDelete = useCallback(async (quizId: string) => {
    try {
      await savedQuizApi.delete(quizId);
      closeDetail();
      fetchQuizzes();
      showToast('Đã xóa bộ đề.', 'success', 2500);
    } catch (err) {
      console.error('Failed to delete quiz', err);
      showToast(extractErrorMessage(err, 'Không thể xóa bộ đề. Vui lòng thử lại.'), 'error');
    }
  }, [closeDetail, fetchQuizzes, showToast]);

  const handleDuplicate = useCallback(async (quizId: string) => {
    try {
      await savedQuizApi.duplicate(quizId);
      fetchQuizzes();
      showToast('Đã nhân bản bộ đề.', 'success', 2500);
    } catch (err) {
      console.error('Failed to duplicate quiz', err);
      showToast(extractErrorMessage(err, 'Không thể nhân bản bộ đề.'), 'error');
    }
  }, [fetchQuizzes, showToast]);

  const handleLoadToBuilder = useCallback((quiz: SavedQuizDetail) => {
    if (!onLoadToBuilder) return;
    const mapped: QuizBuilderQuestion[] = quiz.questions.map(q => {
      const correctText = q.options[q.correct_answer] ?? q.correct_answer;
      return {
        question: q.question_text,
        options: q.options,
        correct: { [q.correct_answer]: correctText },
      };
    });
    onLoadToBuilder(mapped);
    closeDetail();
  }, [onLoadToBuilder, closeDetail]);

  const handleQuizUpdated = useCallback(() => {
    fetchQuizzes();
    // Refresh detail if open
    if (selectedQuizId) {
      savedQuizApi.get(selectedQuizId).then(setDetailQuiz).catch(console.error);
    }
  }, [fetchQuizzes, selectedQuizId]);

  // ---- Pagination ----
  const totalPages = Math.ceil(total / pageSize);

  // ---- Render ----
  return (
    <div className="sq-panel">
      {/* Background stars */}
      <div className="sq-stars">
        {STARS.map(s => (
          <div
            key={s.id}
            className="sq-star"
            style={{
              top: s.top,
              left: s.left,
              width: s.size,
              height: s.size,
              animationDuration: s.duration,
              animationDelay: s.delay,
            }}
          />
        ))}
      </div>

      {/* Header */}
      <div className="sq-header">
        <div className="sq-header-left">
          <Library size={28} />
          <h2>Kho Đề Thi</h2>
          <span className="sq-header-count">{total} bộ đề</span>
        </div>
        <div className="sq-header-right">
          <PanelHelpButton panelKey="saved_quizzes" />
        </div>
      </div>

      <div className="sq-body">
        {/* Sidebar */}
        <aside className="sq-sidebar">
          <div className="sq-sidebar-title">Khóa học</div>
          <button
            className={`sq-sidebar-item ${selectedCourse === 'all' ? 'active' : ''}`}
            onClick={() => { setSelectedCourse('all'); setPage(1); }}
          >
            <FolderOpen size={16} />
            <span>Tất cả</span>
            <span className="sq-sidebar-count">{total}</span>
          </button>
          <button
            className={`sq-sidebar-item ${starredFilter ? 'active starred' : ''}`}
            onClick={() => { setStarredFilter(prev => !prev); setPage(1); }}
          >
            <Star size={16} />
            <span>Đánh dấu</span>
          </button>
          <div className="sq-sidebar-divider" />
          {courses.map(c => (
            <button
              key={c.course_id ?? 'unassigned'}
              className={`sq-sidebar-item ${selectedCourse === c.course_id ? 'active' : ''}`}
              onClick={() => { setSelectedCourse(c.course_id); setPage(1); }}
            >
              <BookOpen size={16} />
              <span className="sq-sidebar-label">{c.course_name || 'Chưa gán khóa học'}</span>
              <span className="sq-sidebar-count">{c.quiz_count}</span>
            </button>
          ))}
          {courses.length === 0 && !loading && (
            <div className="sq-sidebar-empty">Chưa có bộ đề nào</div>
          )}
        </aside>

        {/* Main content */}
        <div className="sq-main">
          {/* Toolbar */}
          <div className="sq-toolbar">
            <div className="sq-search-wrap">
              <Search size={16} className="sq-search-icon" />
              <input
                className="sq-search-input"
                placeholder="Tìm kiếm bộ đề..."
                value={searchTerm}
                onChange={e => setSearchTerm(e.target.value)}
              />
            </div>
            <div className="sq-toolbar-filters">
              <select
                className="sq-select"
                value={difficultyFilter}
                onChange={e => { setDifficultyFilter(e.target.value); setPage(1); }}
              >
                <option value="">Tất cả độ khó</option>
                <option value="easy">Dễ</option>
                <option value="medium">Trung bình</option>
                <option value="hard">Khó</option>
              </select>
              <select
                className="sq-select"
                value={sortBy}
                onChange={e => { setSortBy(e.target.value); setPage(1); }}
              >
                <option value="newest">Mới nhất</option>
                <option value="oldest">Cũ nhất</option>
                <option value="title">Tên A-Z</option>
                <option value="questions">Số câu</option>
              </select>
            </div>
          </div>

          {/* Quiz grid */}
          {loading ? (
            <div className="sq-loading">
              <Loader2 className="spin" size={32} />
              <p>Đang tải...</p>
            </div>
          ) : quizzes.length === 0 ? (
            <div className="sq-empty">
              <Library size={48} strokeWidth={1} />
              <p className="sq-empty-title">Chưa có bộ đề nào</p>
              <p className="sq-empty-desc">
                Tạo quiz từ tài liệu RAG hoặc tự tạo, rồi lưu vào đây để quản lý.
              </p>
            </div>
          ) : (
            <>
              <div className="sq-grid">
                {quizzes.map(quiz => {
                  const src = SOURCE_LABELS[quiz.source] || SOURCE_LABELS.manual;
                  const diff = quiz.difficulty ? DIFFICULTY_LABELS[quiz.difficulty] : null;
                  return (
                    <div
                      key={quiz.id}
                      className="sq-card"
                      onClick={() => openDetail(quiz.id)}
                    >
                      <div className="sq-card-top">
                        <div className="sq-card-title-row">
                          <h3 className="sq-card-title">{quiz.title}</h3>
                          <button
                            className={`sq-star-btn ${quiz.is_starred ? 'starred' : ''}`}
                            onClick={e => handleToggleStar(e, quiz.id)}
                            title={quiz.is_starred ? 'Bỏ đánh dấu' : 'Đánh dấu'}
                          >
                            {quiz.is_starred ? <Star size={16} fill="currentColor" /> : <StarOff size={16} />}
                          </button>
                        </div>
                        {quiz.course_name && (
                          <div className="sq-card-course">{quiz.course_name}</div>
                        )}
                      </div>
                      <div className="sq-card-meta">
                        <span className="sq-card-questions">
                          <BookOpen size={14} />
                          {quiz.question_count} câu
                        </span>
                        {diff && (
                          <span className="sq-badge" style={{ color: diff.color, borderColor: diff.color }}>
                            {diff.label}
                          </span>
                        )}
                        {quiz.language && (
                          <span className="sq-badge sq-badge-lang">
                            {quiz.language.toUpperCase()}
                          </span>
                        )}
                      </div>
                      <div className="sq-card-bottom">
                        <span
                          className="sq-badge sq-badge-source"
                          style={{ color: src.color, borderColor: src.color }}
                        >
                          {src.label}
                        </span>
                        {quiz.tags.length > 0 && (
                          <span className="sq-card-tags">
                            <Tag size={12} />
                            {quiz.tags.slice(0, 2).join(', ')}
                            {quiz.tags.length > 2 && ` +${quiz.tags.length - 2}`}
                          </span>
                        )}
                        <span className="sq-card-time">{timeAgo(quiz.created_at)}</span>
                      </div>
                    </div>
                  );
                })}
              </div>

              {/* Pagination */}
              {totalPages > 1 && (
                <div className="pagination pagination--compact">
                  <button
                    className="pagination-btn"
                    disabled={page <= 1}
                    onClick={() => setPage(p => p - 1)}
                  >
                    ‹ Trước
                  </button>
                  <span className="pagination-info">
                    Trang {page} / {totalPages}
                  </span>
                  <button
                    className="pagination-btn"
                    disabled={page >= totalPages}
                    onClick={() => setPage(p => p + 1)}
                  >
                    Sau ›
                  </button>
                </div>
              )}
            </>
          )}
        </div>
      </div>

      {/* Detail modal */}
      {selectedQuizId && (
        <QuizDetailModal
          quiz={detailQuiz}
          loading={detailLoading}
          onClose={closeDetail}
          onToggleStar={handleToggleStar}
          onDelete={handleDelete}
          onDuplicate={handleDuplicate}
          onLoadToBuilder={onLoadToBuilder ? handleLoadToBuilder : undefined}
          onQuizUpdated={handleQuizUpdated}
        />
      )}
    </div>
  );
};

export default SavedQuizzesPanel;
