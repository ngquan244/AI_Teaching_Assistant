import React, { useState, useEffect, useMemo } from 'react';
import {
  PenSquare,
  Loader2,
  CheckCircle,
  AlertCircle,
  ExternalLink,
  ChevronDown,
  ChevronUp,
  Trash2,
  Info,
  Rocket,
  RefreshCw,
  BookOpen,
  Settings,
  ListChecks,
  GraduationCap,
  Clock,
  Hash,
  Shuffle,
  Send,
  Sparkles,
  Eye,
} from 'lucide-react';
import { canvasQuizApi } from '../api/canvasQuiz';
import { canvasApi } from '../api/canvas';
import type {
  CanvasCourse,
  CanvasQuizCreate,
  CreateCanvasQuizResponse,
  QuizBuilderQuestion,
} from '../types/canvas';

// ============================================================================
// Props
// ============================================================================

export interface QuizBuilderPanelProps {
  /** Questions pre-loaded from RAG generation or QTI import flow */
  questions: QuizBuilderQuestion[];
  /** Clear the injected questions after they are consumed */
  onQuestionsClear?: () => void;
}

// ============================================================================
// Component
// ============================================================================

const QuizBuilderPanel: React.FC<QuizBuilderPanelProps> = ({
  questions: injectedQuestions,
  onQuestionsClear,
}) => {
  // ---- Course selection ----
  const [courses, setCourses] = useState<CanvasCourse[]>([]);
  const [selectedCourseId, setSelectedCourseId] = useState<number | null>(null);
  const [isLoadingCourses, setIsLoadingCourses] = useState(false);
  const [coursesError, setCoursesError] = useState<string | null>(null);

  // ---- Questions in builder ----
  const [builderQuestions, setBuilderQuestions] = useState<QuizBuilderQuestion[]>([]);
  const [expandedQ, setExpandedQ] = useState<number | null>(null);

  // ---- Quiz settings ----
  const [quizSettings, setQuizSettings] = useState<CanvasQuizCreate>({
    title: '',
    description: '',
    quiz_type: 'assignment',
    time_limit: null,
    shuffle_answers: true,
    allowed_attempts: 1,
    published: false,
  });
  const [defaultPoints, setDefaultPoints] = useState(1);

  // ---- Creation state ----
  const [isCreating, setIsCreating] = useState(false);
  const [result, setResult] = useState<CreateCanvasQuizResponse | null>(null);

  // ---- Accept injected questions ----
  useEffect(() => {
    if (injectedQuestions.length > 0) {
      setBuilderQuestions(injectedQuestions);
      setResult(null);
      onQuestionsClear?.();
    }
  }, [injectedQuestions, onQuestionsClear]);

  // ---- Load courses on mount ----
  useEffect(() => {
    loadCourses();
  }, []);

  const loadCourses = async () => {
    setIsLoadingCourses(true);
    setCoursesError(null);
    try {
      const res = await canvasApi.fetchCourses();
      if (res.success) {
        setCourses(res.courses);
        // Auto-select from localStorage
        const savedId = localStorage.getItem('canvas_selected_course_id');
        if (savedId) {
          const id = parseInt(savedId, 10);
          if (res.courses.some((c: CanvasCourse) => c.id === id)) {
            setSelectedCourseId(id);
          }
        }
      } else {
        setCoursesError(res.error || 'Failed to load courses');
      }
    } catch {
      setCoursesError('Không kết nối được Canvas. Kiểm tra token ở phần Cài đặt.');
    } finally {
      setIsLoadingCourses(false);
    }
  };

  const handleCourseChange = (e: React.ChangeEvent<HTMLSelectElement>) => {
    const id = parseInt(e.target.value, 10) || null;
    setSelectedCourseId(id);
    if (id) localStorage.setItem('canvas_selected_course_id', String(id));
  };

  // ---- Remove a question ----
  const removeQuestion = (idx: number) => {
    setBuilderQuestions((prev) => prev.filter((_, i) => i !== idx));
  };

  // ---- Create quiz ----
  const handleCreateQuiz = async () => {
    if (!selectedCourseId || builderQuestions.length === 0) return;

    setIsCreating(true);
    setResult(null);

    try {
      const directQuestions = builderQuestions.map((q) => {
        const correctObj = q.correct ?? {};
        const correctKeys = Object.keys(correctObj);
        return {
          question_text: q.question,
          question_type:
            correctKeys.length > 1
              ? 'multiple_answers_question'
              : 'multiple_choice_question',
          options: q.options ?? {},
          correct_keys: correctKeys,
          points: defaultPoints,
        };
      });

      console.log('[QuizBuilder] Creating quiz with', directQuestions.length, 'questions for course', selectedCourseId);

      const res = await canvasQuizApi.createFullQuiz({
        course_id: selectedCourseId,
        quiz: quizSettings,
        direct_questions: directQuestions,
        source_questions: [],
        default_points: defaultPoints,
      });

      console.log('[QuizBuilder] Result:', res);
      setResult(res);
    } catch (err) {
      console.error('[QuizBuilder] Unexpected error:', err);
      setResult({ success: false, error: String(err) });
    } finally {
      setIsCreating(false);
    }
  };

  // ---- Helpers ----
  const canCreate =
    selectedCourseId &&
    builderQuestions.length > 0 &&
    quizSettings.title.trim().length > 0;

  const selectedCourseName =
    courses.find((c) => c.id === selectedCourseId)?.name || '';

  // Decorative stars
  const qbStars = useMemo(
    () =>
      Array.from({ length: 20 }, (_, i) => ({
        id: i,
        top: `${Math.random() * 100}%`,
        left: `${Math.random() * 100}%`,
        duration: `${3 + Math.random() * 4}s`,
        delay: `${Math.random() * 5}s`,
        size: `${1.5 + Math.random() * 1.5}px`,
      })),
    [],
  );

  // ============================================================================
  // Render
  // ============================================================================
  return (
    <div className="qb-panel">
      {/* Decorative background */}
      <div className="qb-bg-orbs">
        <div className="qb-orb qb-orb-1" />
        <div className="qb-orb qb-orb-2" />
        <div className="qb-orb qb-orb-3" />
      </div>
      <div className="qb-stars">
        {qbStars.map((s) => (
          <div
            key={s.id}
            className="qb-star"
            style={{
              top: s.top,
              left: s.left,
              animationDuration: s.duration,
              animationDelay: s.delay,
              width: s.size,
              height: s.size,
            }}
          />
        ))}
      </div>

      {/* ---- Header ---- */}
      <div className="qb-header">
        <div className="qb-header-icon">
          <GraduationCap size={22} />
        </div>
        <div className="qb-header-text">
          <h2>Tạo Canvas Quiz</h2>
          <p className="qb-subtitle">
            Soạn câu hỏi và đẩy lên Canvas LMS
          </p>
        </div>
        <div className="qb-header-badge">
          <Sparkles size={12} />
          <span>Canvas LMS</span>
        </div>
      </div>

      {/* ---- Result banner ---- */}
      {result && (
        <div className={`qb-result ${result.success ? 'success' : 'error'}`}>
          <div className="qb-result-card">
            <div className={`qb-result-stripe ${result.success ? 'success' : 'error'}`} />
            <div className={`qb-result-icon ${result.success ? 'success' : 'error'}`}>
              {result.success ? <CheckCircle size={18} /> : <AlertCircle size={18} />}
            </div>
            <div className="qb-result-content">
              <span className="qb-result-title">
                {result.success ? 'Tạo Canvas Quiz thành công!' : 'Tạo thất bại'}
              </span>
              <span className="qb-result-desc">
                {result.success
                  ? `Đã thêm ${result.questions_added ?? 0} câu hỏi lên Canvas`
                  : (result.error || 'Lỗi không xác định')}
              </span>
            </div>
            {result.success && result.quiz_url && (
              <a
                href={result.quiz_url}
                target="_blank"
                rel="noopener noreferrer"
                className="qb-btn qb-btn-canvas-link"
              >
                <Eye size={14} /> Mở trên Canvas <ExternalLink size={11} />
              </a>
            )}
            <button
              className="qb-result-close"
              onClick={() => setResult(null)}
              title="Đóng"
            >
              ×
            </button>
          </div>
        </div>
      )}

      <div className="qb-body">
        {/* ============================================================
            LEFT COLUMN — Quiz Settings
            ============================================================ */}
        <div className="qb-settings">
          {/* Section: Course */}
          <div className="qb-section">
            <div className="qb-section-title">
              <BookOpen size={15} />
              <span>Khóa học</span>
            </div>
            <div className="qb-course-row">
              <select
                value={selectedCourseId ?? ''}
                onChange={handleCourseChange}
                disabled={isLoadingCourses}
                className="qb-select"
              >
                <option value="">-- Chọn khóa học --</option>
                {courses.map((c) => (
                  <option key={c.id} value={c.id}>
                    {c.name} ({c.course_code})
                  </option>
                ))}
              </select>
              <button
                className="qb-btn qb-btn-icon"
                onClick={loadCourses}
                disabled={isLoadingCourses}
                title="Tải lại danh sách"
              >
                {isLoadingCourses ? (
                  <Loader2 size={15} className="spin" />
                ) : (
                  <RefreshCw size={15} />
                )}
              </button>
            </div>
            {coursesError && (
              <span className="qb-field-error">{coursesError}</span>
            )}
          </div>

          {/* Section: Quiz Info */}
          <div className="qb-section">
            <div className="qb-section-title">
              <Settings size={15} />
              <span>Thông tin bài kiểm tra</span>
            </div>

            <label className="qb-label">
              <span className="qb-label-text">Tiêu đề <span className="qb-required">*</span></span>
              <input
                type="text"
                className="qb-input"
                placeholder="VD: Kiểm tra giữa kỳ"
                value={quizSettings.title}
                onChange={(e) =>
                  setQuizSettings((s) => ({ ...s, title: e.target.value }))
                }
              />
            </label>

            <label className="qb-label">
              <span className="qb-label-text">Mô tả</span>
              <textarea
                className="qb-textarea"
                rows={2}
                placeholder="Mô tả ngắn (không bắt buộc)…"
                value={quizSettings.description || ''}
                onChange={(e) =>
                  setQuizSettings((s) => ({ ...s, description: e.target.value }))
                }
              />
            </label>

            <label className="qb-label">
              <span className="qb-label-text">Loại bài</span>
              <select
                className="qb-select"
                value={quizSettings.quiz_type}
                onChange={(e) =>
                  setQuizSettings((s) => ({
                    ...s,
                    quiz_type: e.target.value as CanvasQuizCreate['quiz_type'],
                  }))
                }
              >
                <option value="assignment">Bài kiểm tra có điểm</option>
                <option value="practice_quiz">Bài luyện tập</option>
                <option value="graded_survey">Khảo sát có điểm</option>
                <option value="survey">Khảo sát không điểm</option>
              </select>
            </label>
          </div>

          {/* Section: Options */}
          <div className="qb-section">
            <div className="qb-section-title">
              <ListChecks size={15} />
              <span>Tùy chọn</span>
            </div>

            <div className="qb-options-grid">
              <label className="qb-label qb-compact">
                <span className="qb-label-text"><Clock size={13} /> Thời gian</span>
                <div className="qb-input-suffix">
                  <input
                    type="number"
                    className="qb-input"
                    min={0}
                    placeholder="∞"
                    value={quizSettings.time_limit ?? ''}
                    onChange={(e) =>
                      setQuizSettings((s) => ({
                        ...s,
                        time_limit: e.target.value
                          ? parseInt(e.target.value, 10)
                          : null,
                      }))
                    }
                  />
                  <span className="qb-suffix">phút</span>
                </div>
              </label>
              <label className="qb-label qb-compact">
                <span className="qb-label-text"><Hash size={13} /> Lượt làm</span>
                <input
                  type="number"
                  className="qb-input"
                  min={-1}
                  value={quizSettings.allowed_attempts}
                  onChange={(e) =>
                    setQuizSettings((s) => ({
                      ...s,
                      allowed_attempts: parseInt(e.target.value, 10) || 1,
                    }))
                  }
                />
                <span className="qb-hint">-1 = không giới hạn</span>
              </label>
              <label className="qb-label qb-compact">
                <span className="qb-label-text">Điểm / Câu</span>
                <input
                  type="number"
                  className="qb-input"
                  min={0}
                  step={0.5}
                  value={defaultPoints}
                  onChange={(e) =>
                    setDefaultPoints(parseFloat(e.target.value) || 1)
                  }
                />
              </label>
            </div>

            {/* Toggle switches */}
            <div className="qb-toggles">
              <label className="qb-toggle">
                <div className="qb-toggle-info">
                  <Shuffle size={14} />
                  <span>Xáo trộn đáp án</span>
                </div>
                <div className={`qb-switch ${quizSettings.shuffle_answers ? 'on' : ''}`}
                  onClick={() => setQuizSettings((s) => ({ ...s, shuffle_answers: !s.shuffle_answers }))}
                >
                  <div className="qb-switch-thumb" />
                </div>
              </label>
              <label className="qb-toggle">
                <div className="qb-toggle-info">
                  <Send size={14} />
                  <span>Xuất bản ngay</span>
                </div>
                <div className={`qb-switch ${quizSettings.published ? 'on' : ''}`}
                  onClick={() => setQuizSettings((s) => ({ ...s, published: !s.published }))}
                >
                  <div className="qb-switch-thumb" />
                </div>
              </label>
            </div>
          </div>
        </div>

        {/* ============================================================
            RIGHT COLUMN — Question List
            ============================================================ */}
        <div className="qb-questions">
          <div className="qb-questions-header">
            <h3>
              <PenSquare size={15} />
              Câu hỏi
              <span className="qb-count">{builderQuestions.length}</span>
            </h3>
            {builderQuestions.length > 0 && (
              <div className="qb-total-pts">
                Tổng: {builderQuestions.length * defaultPoints} điểm
              </div>
            )}
          </div>

          {builderQuestions.length === 0 ? (
            <div className="qb-empty">
              <div className="qb-empty-icon">
                <BookOpen size={36} strokeWidth={1.5} />
              </div>
              <p className="qb-empty-title">Chưa có câu hỏi nào</p>
              <p className="qb-hint">
                Tạo câu hỏi từ tab <strong>RAG Tài Liệu</strong>,
                sau đó nhấn <strong>"Tạo Canvas Quiz"</strong> để đưa sang đây.
              </p>
            </div>
          ) : (
            <div className="qb-question-list">
              {builderQuestions.map((q, idx) => {
                const isExpanded = expandedQ === idx;
                const correctKeys = Object.keys(q.correct ?? {});
                return (
                  <div
                    key={idx}
                    className={`qb-question-card ${isExpanded ? 'expanded' : ''}`}
                  >
                    <div
                      className="qb-question-row"
                      onClick={() => setExpandedQ(isExpanded ? null : idx)}
                    >
                      <span className="qb-q-number">{idx + 1}</span>
                      <span className="qb-q-text">
                        {stripHtml(q.question).slice(0, 100)}
                        {stripHtml(q.question).length > 100 ? '…' : ''}
                      </span>
                      <div className="qb-q-actions">
                        <button
                          className="qb-btn qb-btn-icon qb-btn-danger"
                          onClick={(e) => {
                            e.stopPropagation();
                            removeQuestion(idx);
                          }}
                          title="Xóa câu hỏi"
                        >
                          <Trash2 size={13} />
                        </button>
                        <div className={`qb-chevron ${isExpanded ? 'up' : ''}`}>
                          <ChevronDown size={15} />
                        </div>
                      </div>
                    </div>
                    <div
                      className="qb-question-detail-wrapper"
                      style={{
                        maxHeight: isExpanded ? '500px' : '0px',
                        opacity: isExpanded ? 1 : 0,
                      }}
                    >
                      <div className="qb-question-detail">
                        <div
                          className="qb-q-full-text"
                          dangerouslySetInnerHTML={{ __html: q.question }}
                        />
                        <ul className="qb-opts">
                          {Object.entries(q.options ?? {}).map(
                            ([letter, text]) => {
                              const isCorrect = correctKeys.includes(letter);
                              return (
                                <li
                                  key={letter}
                                  className={`qb-opt ${isCorrect ? 'correct' : ''}`}
                                >
                                  <span className={`qb-opt-letter ${isCorrect ? 'correct' : ''}`}>
                                    {letter}
                                  </span>
                                  <span className="qb-opt-text">{text}</span>
                                  {isCorrect && (
                                    <CheckCircle
                                      size={14}
                                      className="qb-correct-icon"
                                    />
                                  )}
                                </li>
                              );
                            },
                          )}
                        </ul>
                      </div>
                    </div>
                  </div>
                );
              })}
            </div>
          )}
        </div>
      </div>

      {/* ---- Footer ---- */}
      <div className="qb-footer">
        <div className="qb-footer-info">
          {selectedCourseName && (
            <span className="qb-footer-course">{selectedCourseName}</span>
          )}
          <span className="qb-footer-stats">
            {builderQuestions.length} câu hỏi
            {builderQuestions.length > 0 && ` · ${builderQuestions.length * defaultPoints} điểm`}
          </span>
        </div>
        {result?.success ? (
          <button
            className="qb-btn qb-btn-primary qb-btn-create qb-btn-new"
            onClick={() => {
              setResult(null);
              setQuizSettings((s) => ({ ...s, title: '', description: '' }));
            }}
          >
            <RefreshCw size={17} />
            <span>Tạo bài mới</span>
          </button>
        ) : (
          <button
            className="qb-btn qb-btn-primary qb-btn-create"
            disabled={!canCreate || isCreating}
            onClick={handleCreateQuiz}
          >
            {isCreating ? (
              <>
                <Loader2 size={17} className="spin" />
                <span>Đang tạo…</span>
              </>
            ) : (
              <>
                <Rocket size={17} />
                <span>Tạo Canvas Quiz</span>
              </>
            )}
          </button>
        )}
      </div>

      {/* ---- Scoped Styles ---- */}
      <style>{`
        /* =============== QUIZ BUILDER PANEL =============== */
        .qb-panel {
          position: relative;
          display: flex;
          flex-direction: column;
          height: 100%;
          background: linear-gradient(165deg, #0c0e16 0%, #131525 40%, #0f1320 100%);
          color: #e2e8f0;
          font-family: 'Inter', system-ui, -apple-system, sans-serif;
          overflow: hidden;
        }

        /* ---- Decorative background ---- */
        .qb-bg-orbs { position: absolute; inset: 0; pointer-events: none; z-index: 0; overflow: hidden; }
        .qb-orb {
          position: absolute;
          border-radius: 50%;
          filter: blur(80px);
          opacity: 0.07;
          animation: qb-float 20s ease-in-out infinite;
        }
        .qb-orb-1 { width: 400px; height: 400px; top: -100px; right: -80px; background: #818cf8; animation-delay: 0s; }
        .qb-orb-2 { width: 300px; height: 300px; bottom: -60px; left: -50px; background: #38bdf8; animation-delay: -7s; }
        .qb-orb-3 { width: 250px; height: 250px; top: 40%; left: 50%; background: #a78bfa; animation-delay: -14s; }

        .qb-stars { position: absolute; inset: 0; pointer-events: none; z-index: 0; }
        .qb-star {
          position: absolute;
          border-radius: 50%;
          background: #fff;
          opacity: 0;
          animation: qb-twinkle var(--dur, 4s) ease-in-out infinite;
        }
        @keyframes qb-float {
          0%, 100% { transform: translate(0, 0) scale(1); }
          33% { transform: translate(30px, -20px) scale(1.05); }
          66% { transform: translate(-20px, 20px) scale(0.95); }
        }
        @keyframes qb-twinkle {
          0%, 100% { opacity: 0; }
          50% { opacity: 0.4; }
        }

        /* All content above background */
        .qb-header, .qb-result, .qb-body, .qb-footer {
          position: relative;
          z-index: 1;
        }

        /* ---- Header ---- */
        .qb-header {
          display: flex;
          align-items: center;
          gap: 14px;
          padding: 18px 24px 14px;
          border-bottom: 1px solid rgba(255,255,255,0.05);
        }
        .qb-header-icon {
          width: 40px; height: 40px;
          display: flex; align-items: center; justify-content: center;
          border-radius: 12px;
          background: linear-gradient(135deg, rgba(56,189,248,0.15), rgba(129,140,248,0.15));
          color: #38bdf8;
          flex-shrink: 0;
        }
        .qb-header-text { flex: 1; }
        .qb-header h2 {
          margin: 0;
          font-size: 1.15rem;
          font-weight: 700;
          background: linear-gradient(135deg, #38bdf8 0%, #818cf8 50%, #a78bfa 100%);
          -webkit-background-clip: text;
          -webkit-text-fill-color: transparent;
          background-clip: text;
        }
        .qb-subtitle {
          margin: 2px 0 0;
          font-size: 0.78rem;
          color: #4a5568;
        }
        .qb-header-badge {
          display: flex;
          align-items: center;
          gap: 5px;
          padding: 4px 10px;
          border-radius: 20px;
          background: rgba(56,189,248,0.08);
          border: 1px solid rgba(56,189,248,0.15);
          font-size: 0.7rem;
          font-weight: 600;
          color: #38bdf8;
          letter-spacing: 0.02em;
        }

        /* ---- Result banner ---- */
        .qb-result {
          padding: 12px 24px;
          animation: qb-slideDown 0.35s ease-out;
        }
        .qb-result-card {
          display: flex;
          align-items: center;
          gap: 12px;
          padding: 12px 16px;
          border-radius: 10px;
          position: relative;
          overflow: hidden;
        }
        .qb-result.success .qb-result-card {
          background: linear-gradient(135deg, rgba(16,185,129,0.06), rgba(56,189,248,0.03));
          border: 1px solid rgba(16,185,129,0.12);
        }
        .qb-result.error .qb-result-card {
          background: linear-gradient(135deg, rgba(239,68,68,0.06), rgba(239,68,68,0.02));
          border: 1px solid rgba(239,68,68,0.12);
        }
        .qb-result-stripe {
          position: absolute;
          left: 0; top: 0; bottom: 0;
          width: 3px;
        }
        .qb-result-stripe.success { background: linear-gradient(180deg, #34d399, #38bdf8); }
        .qb-result-stripe.error   { background: linear-gradient(180deg, #f87171, #fb923c); }
        .qb-result-icon {
          width: 32px; height: 32px;
          display: flex; align-items: center; justify-content: center;
          border-radius: 9px;
          flex-shrink: 0;
        }
        .qb-result-icon.success { background: rgba(16,185,129,0.1); color: #34d399; }
        .qb-result-icon.error   { background: rgba(239,68,68,0.1); color: #f87171; }
        .qb-result-content {
          flex: 1;
          display: flex;
          flex-direction: column;
          gap: 1px;
          min-width: 0;
        }
        .qb-result-title {
          font-size: 0.84rem;
          font-weight: 600;
          color: #e2e8f0;
        }
        .qb-result-desc {
          font-size: 0.75rem;
          color: #64748b;
          white-space: nowrap;
          overflow: hidden;
          text-overflow: ellipsis;
        }
        .qb-btn-canvas-link {
          display: inline-flex;
          align-items: center;
          gap: 5px;
          padding: 7px 14px;
          border-radius: 8px;
          background: linear-gradient(135deg, #3b82f6, #2563eb);
          border: none;
          color: #fff;
          font-size: 0.78rem;
          font-weight: 600;
          text-decoration: none;
          white-space: nowrap;
          flex-shrink: 0;
          transition: all 0.2s;
          box-shadow: 0 2px 8px rgba(59,130,246,0.25);
        }
        .qb-btn-canvas-link:hover {
          filter: brightness(1.12);
          box-shadow: 0 4px 14px rgba(59,130,246,0.35);
          transform: translateY(-1px);
        }
        .qb-result-close {
          display: flex;
          align-items: center;
          justify-content: center;
          width: 24px; height: 24px;
          border-radius: 6px;
          border: none;
          background: transparent;
          color: #475569;
          font-size: 1.1rem;
          cursor: pointer;
          flex-shrink: 0;
          transition: all 0.15s;
          line-height: 1;
        }
        .qb-result-close:hover { background: rgba(255,255,255,0.06); color: #94a3b8; }
        @keyframes qb-slideDown {
          from { opacity: 0; transform: translateY(-8px); }
          to { opacity: 1; transform: translateY(0); }
        }

        /* ---- Body (two columns) ---- */
        .qb-body {
          flex: 1;
          display: flex;
          overflow: hidden;
          min-height: 0;
        }

        /* ---- Settings column ---- */
        .qb-settings {
          width: 340px;
          min-width: 290px;
          max-width: 340px;
          padding: 16px 20px;
          border-right: 1px solid rgba(255,255,255,0.05);
          overflow-y: auto;
          overflow-x: hidden;
          display: flex;
          flex-direction: column;
          gap: 4px;
        }
        .qb-section {
          padding: 12px 0;
          border-bottom: 1px solid rgba(255,255,255,0.04);
        }
        .qb-section:last-child { border-bottom: none; }
        .qb-section-title {
          display: flex;
          align-items: center;
          gap: 8px;
          margin-bottom: 12px;
          font-size: 0.75rem;
          font-weight: 700;
          text-transform: uppercase;
          letter-spacing: 0.06em;
          color: #64748b;
        }
        .qb-section-title svg { opacity: 0.7; }

        .qb-label {
          display: flex;
          flex-direction: column;
          gap: 5px;
          margin-bottom: 12px;
        }
        .qb-label-text {
          display: flex;
          align-items: center;
          gap: 5px;
          font-size: 0.78rem;
          font-weight: 500;
          color: #8892a4;
        }
        .qb-required { color: #f87171; }

        .qb-input, .qb-select, .qb-textarea {
          padding: 8px 11px;
          border-radius: 8px;
          border: 1px solid rgba(255,255,255,0.08);
          background: rgba(255,255,255,0.03);
          color: #e2e8f0;
          font-size: 0.84rem;
          outline: none;
          transition: all 0.2s;
        }
        .qb-input:focus, .qb-select:focus, .qb-textarea:focus {
          border-color: rgba(56,189,248,0.4);
          background: rgba(56,189,248,0.03);
          box-shadow: 0 0 0 3px rgba(56,189,248,0.06);
        }
        .qb-input::placeholder, .qb-textarea::placeholder {
          color: #3e4556;
        }
        .qb-textarea { resize: vertical; font-family: inherit; min-height: 52px; }
        .qb-select { cursor: pointer; }
        .qb-select option { background: #1a1d2e; }

        .qb-course-row {
          display: flex;
          gap: 6px;
          min-width: 0;
        }
        .qb-course-row .qb-select { flex: 1; min-width: 0; overflow: hidden; text-overflow: ellipsis; }

        .qb-options-grid {
          display: grid;
          grid-template-columns: 1fr 1fr;
          gap: 10px;
          margin-bottom: 14px;
        }
        .qb-options-grid > :last-child {
          grid-column: 1 / -1;
        }
        .qb-compact { margin-bottom: 0; }
        .qb-compact .qb-input { text-align: center; padding: 7px 6px; }
        .qb-input-suffix {
          position: relative;
          display: flex;
          align-items: center;
        }
        .qb-input-suffix .qb-input {
          width: 100%;
          padding-right: 34px;
        }
        .qb-suffix {
          position: absolute;
          right: 9px;
          font-size: 0.72rem;
          color: #475569;
          pointer-events: none;
        }

        .qb-hint {
          font-size: 0.7rem;
          color: #4a5568;
          margin-top: 2px;
        }
        .qb-field-error {
          font-size: 0.76rem;
          color: #f87171;
          margin-top: 4px;
        }

        /* Toggle switches */
        .qb-toggles {
          display: flex;
          flex-direction: column;
          gap: 8px;
        }
        .qb-toggle {
          display: flex;
          align-items: center;
          justify-content: space-between;
          padding: 8px 10px;
          border-radius: 8px;
          background: rgba(255,255,255,0.02);
          border: 1px solid rgba(255,255,255,0.04);
          cursor: pointer;
          transition: background 0.15s;
        }
        .qb-toggle:hover { background: rgba(255,255,255,0.04); }
        .qb-toggle-info {
          display: flex;
          align-items: center;
          gap: 8px;
          font-size: 0.8rem;
          color: #94a3b8;
        }
        .qb-switch {
          width: 36px; height: 20px;
          border-radius: 10px;
          background: rgba(255,255,255,0.1);
          position: relative;
          cursor: pointer;
          transition: background 0.2s;
          flex-shrink: 0;
        }
        .qb-switch.on { background: rgba(56,189,248,0.5); }
        .qb-switch-thumb {
          position: absolute;
          top: 2px; left: 2px;
          width: 16px; height: 16px;
          border-radius: 50%;
          background: #fff;
          transition: transform 0.2s;
          box-shadow: 0 1px 3px rgba(0,0,0,0.3);
        }
        .qb-switch.on .qb-switch-thumb { transform: translateX(16px); }

        /* ---- Questions column ---- */
        .qb-questions {
          flex: 1;
          display: flex;
          flex-direction: column;
          min-width: 0;
          overflow: hidden;
        }
        .qb-questions-header {
          display: flex;
          align-items: center;
          justify-content: space-between;
          padding: 16px 20px 10px;
        }
        .qb-questions-header h3 {
          margin: 0;
          display: flex;
          align-items: center;
          gap: 8px;
          font-size: 0.88rem;
          font-weight: 600;
          color: #8892a4;
        }
        .qb-count {
          display: inline-flex;
          align-items: center;
          justify-content: center;
          min-width: 22px;
          height: 22px;
          padding: 0 6px;
          border-radius: 11px;
          background: rgba(56,189,248,0.1);
          color: #38bdf8;
          font-size: 0.72rem;
          font-weight: 700;
        }
        .qb-total-pts {
          font-size: 0.75rem;
          color: #4a5568;
          padding: 3px 10px;
          border-radius: 12px;
          background: rgba(255,255,255,0.03);
          border: 1px solid rgba(255,255,255,0.05);
        }

        /* Empty state */
        .qb-empty {
          flex: 1;
          display: flex;
          flex-direction: column;
          align-items: center;
          justify-content: center;
          gap: 12px;
          text-align: center;
          padding: 40px 30px;
        }
        .qb-empty-icon {
          width: 64px; height: 64px;
          display: flex; align-items: center; justify-content: center;
          border-radius: 18px;
          background: linear-gradient(135deg, rgba(56,189,248,0.08), rgba(129,140,248,0.08));
          color: #475569;
          margin-bottom: 4px;
        }
        .qb-empty-title {
          margin: 0;
          font-size: 0.92rem;
          font-weight: 600;
          color: #64748b;
        }
        .qb-empty .qb-hint {
          max-width: 280px;
          line-height: 1.5;
        }

        /* Question list */
        .qb-question-list {
          flex: 1;
          overflow-y: auto;
          padding: 0 20px 16px;
          display: flex;
          flex-direction: column;
          gap: 5px;
        }
        .qb-question-card {
          border-radius: 10px;
          border: 1px solid rgba(255,255,255,0.05);
          background: rgba(255,255,255,0.015);
          overflow: hidden;
          transition: all 0.2s;
        }
        .qb-question-card:hover {
          border-color: rgba(56,189,248,0.15);
          background: rgba(255,255,255,0.025);
        }
        .qb-question-card.expanded {
          border-color: rgba(56,189,248,0.2);
          background: rgba(56,189,248,0.02);
        }
        .qb-question-row {
          display: flex;
          align-items: center;
          gap: 10px;
          padding: 9px 12px;
          cursor: pointer;
          user-select: none;
        }
        .qb-q-number {
          flex-shrink: 0;
          width: 28px; height: 28px;
          display: flex; align-items: center; justify-content: center;
          border-radius: 8px;
          background: linear-gradient(135deg, rgba(56,189,248,0.12), rgba(129,140,248,0.12));
          color: #38bdf8;
          font-size: 0.76rem;
          font-weight: 700;
        }
        .qb-q-text {
          flex: 1;
          font-size: 0.83rem;
          color: #b8c4d4;
          white-space: nowrap;
          overflow: hidden;
          text-overflow: ellipsis;
          line-height: 1.4;
        }
        .qb-q-actions {
          display: flex;
          align-items: center;
          gap: 4px;
          flex-shrink: 0;
        }
        .qb-chevron {
          display: flex;
          align-items: center;
          color: #475569;
          transition: transform 0.25s;
        }
        .qb-chevron.up { transform: rotate(-180deg); }

        /* Expandable detail */
        .qb-question-detail-wrapper {
          overflow: hidden;
          transition: max-height 0.3s ease, opacity 0.25s ease;
        }
        .qb-question-detail {
          padding: 4px 14px 14px 50px;
        }
        .qb-q-full-text {
          font-size: 0.83rem;
          color: #b8c4d4;
          margin-bottom: 10px;
          line-height: 1.55;
        }
        .qb-opts {
          list-style: none;
          padding: 0;
          margin: 0;
          display: flex;
          flex-direction: column;
          gap: 4px;
        }
        .qb-opt {
          display: flex;
          align-items: center;
          gap: 8px;
          padding: 7px 10px;
          border-radius: 7px;
          font-size: 0.8rem;
          background: rgba(255,255,255,0.025);
          border: 1px solid rgba(255,255,255,0.04);
          color: #8892a4;
          transition: all 0.15s;
        }
        .qb-opt.correct {
          background: rgba(16,185,129,0.06);
          border-color: rgba(16,185,129,0.15);
          color: #34d399;
        }
        .qb-opt-letter {
          font-weight: 700;
          min-width: 20px;
          text-align: center;
          font-size: 0.75rem;
          padding: 2px 0;
          border-radius: 4px;
          background: rgba(255,255,255,0.04);
        }
        .qb-opt-letter.correct {
          background: rgba(16,185,129,0.12);
          color: #34d399;
        }
        .qb-opt-text { flex: 1; }
        .qb-correct-icon { flex-shrink: 0; margin-left: auto; }

        /* ---- Footer ---- */
        .qb-footer {
          display: flex;
          align-items: center;
          justify-content: space-between;
          padding: 12px 24px;
          border-top: 1px solid rgba(255,255,255,0.05);
          background: rgba(0,0,0,0.2);
          backdrop-filter: blur(10px);
        }
        .qb-footer-info {
          display: flex;
          flex-direction: column;
          gap: 2px;
        }
        .qb-footer-course {
          font-size: 0.8rem;
          font-weight: 600;
          color: #94a3b8;
        }
        .qb-footer-stats {
          font-size: 0.75rem;
          color: #4a5568;
        }

        /* ---- Buttons ---- */
        .qb-btn {
          display: inline-flex;
          align-items: center;
          gap: 7px;
          border: none;
          font-size: 0.84rem;
          font-weight: 600;
          cursor: pointer;
          transition: all 0.2s;
          font-family: inherit;
        }
        .qb-btn:disabled {
          opacity: 0.4;
          cursor: not-allowed;
        }
        .qb-btn-create {
          padding: 10px 22px;
          border-radius: 10px;
          background: linear-gradient(135deg, #3b82f6 0%, #7c3aed 100%);
          color: #fff;
          box-shadow: 0 2px 12px rgba(59,130,246,0.2);
          position: relative;
          overflow: hidden;
        }
        .qb-btn-create::before {
          content: '';
          position: absolute;
          inset: 0;
          background: linear-gradient(135deg, transparent, rgba(255,255,255,0.1));
          opacity: 0;
          transition: opacity 0.2s;
        }
        .qb-btn-create:hover:not(:disabled)::before { opacity: 1; }
        .qb-btn-create:hover:not(:disabled) {
          transform: translateY(-1px);
          box-shadow: 0 4px 20px rgba(59,130,246,0.3);
        }
        .qb-btn-create:active:not(:disabled) {
          transform: translateY(0);
        }
        .qb-btn-new {
          background: linear-gradient(135deg, #10b981 0%, #38bdf8 100%) !important;
          box-shadow: 0 2px 12px rgba(16,185,129,0.2) !important;
        }
        .qb-btn-new:hover {
          box-shadow: 0 4px 20px rgba(16,185,129,0.3) !important;
        }
        .qb-btn-primary {
          background: linear-gradient(135deg, #3b82f6, #8b5cf6);
          color: #fff;
          padding: 8px 16px;
          border-radius: 8px;
        }
        .qb-btn-primary:hover:not(:disabled) {
          filter: brightness(1.1);
        }
        .qb-btn-ghost {
          background: rgba(255,255,255,0.04);
          border: 1px solid rgba(255,255,255,0.1) !important;
          color: #94a3b8;
          padding: 6px 14px;
          font-size: 0.78rem;
          border-radius: 7px;
        }
        .qb-btn-ghost:hover { 
          border-color: rgba(255,255,255,0.2) !important;
          background: rgba(255,255,255,0.06);
        }
        .qb-btn-link {
          background: none;
          color: #38bdf8;
          padding: 5px 12px;
          border-radius: 6px;
          font-size: 0.78rem;
          text-decoration: none;
        }
        .qb-btn-link:hover { background: rgba(56,189,248,0.08); }
        .qb-btn-icon {
          padding: 6px;
          border-radius: 7px;
          background: transparent;
          color: #4a5568;
        }
        .qb-btn-icon:hover { background: rgba(255,255,255,0.06); color: #94a3b8; }
        .qb-btn-danger:hover { color: #f87171 !important; background: rgba(239,68,68,0.08) !important; }

        .spin { animation: qb-spin 1s linear infinite; }
        @keyframes qb-spin { to { transform: rotate(360deg); } }

        /* Scrollbars */
        .qb-question-list::-webkit-scrollbar,
        .qb-settings::-webkit-scrollbar { width: 5px; }
        .qb-question-list::-webkit-scrollbar-track,
        .qb-settings::-webkit-scrollbar-track { background: transparent; }
        .qb-question-list::-webkit-scrollbar-thumb,
        .qb-settings::-webkit-scrollbar-thumb {
          background: rgba(255,255,255,0.07);
          border-radius: 3px;
        }
        .qb-question-list::-webkit-scrollbar-thumb:hover,
        .qb-settings::-webkit-scrollbar-thumb:hover {
          background: rgba(255,255,255,0.12);
        }
      `}</style>
    </div>
  );
};

// ============================================================================
// Helpers
// ============================================================================

function stripHtml(html: string): string {
  const div = document.createElement('div');
  div.innerHTML = html;
  return div.textContent || div.innerText || '';
}

export default QuizBuilderPanel;
