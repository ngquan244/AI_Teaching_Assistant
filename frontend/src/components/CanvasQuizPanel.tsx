import React, { useState, useEffect, useMemo, useCallback } from 'react';
import {
  PenSquare,
  ChevronRight,
  ChevronLeft,
  Loader2,
  BookOpen,
  CheckCircle,
  AlertCircle,
  RefreshCw,
  Library,
  Shuffle,
  Plus,
  Trash2,
  ExternalLink,
  Search,
  ChevronDown,
  ChevronUp,
  Info,
} from 'lucide-react';
import PanelHelpButton from './PanelHelpButton';
import { canvasQuizApi } from '../api/canvasQuiz';
import { canvasApi } from '../api/canvas';
import type {
  CanvasCourse,
  AssessmentQuestionBank,
  AssessmentQuestion,
  CanvasQuizCreate,
  BankQuestionSelect,
  QuestionGroupConfig,
  CreateCanvasQuizResponse,
} from '../types/canvas';

// ============================================================================
// Types
// ============================================================================

type WizardStep = 1 | 2 | 3;

interface QuestionGroupRow {
  id: string; // internal key
  bank_id: number;
  bank_title: string;
  name: string;
  pick_count: number;
  question_points: number;
}

interface SelectedBankQuestions {
  bank_id: number;
  bank_title: string;
  question_ids: number[];
}

// ============================================================================
// Decorative helpers (stars)
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

const STARS = makeStars(30);

// ============================================================================
// Component
// ============================================================================

export interface CanvasQuizPanelProps {
  /** Pre-select a course when navigating from another panel */
  initialCourseId?: number;
  initialCourseName?: string;
}

const CanvasQuizPanel: React.FC<CanvasQuizPanelProps> = ({
  initialCourseId,
  initialCourseName,
}) => {
  // ----- Wizard state -----
  const [step, setStep] = useState<WizardStep>(1);

  // ----- Course state -----
  const [courses, setCourses] = useState<CanvasCourse[]>([]);
  const [coursesLoading, setCoursesLoading] = useState(false);
  const [selectedCourseId, setSelectedCourseId] = useState<number | null>(
    initialCourseId ?? null,
  );
  const [selectedCourseName, setSelectedCourseName] = useState(
    initialCourseName ?? '',
  );

  // ----- Quiz settings (Step 1) -----
  const [quizTitle, setQuizTitle] = useState('');
  const [quizDescription, setQuizDescription] = useState('');
  const [quizType, setQuizType] = useState<CanvasQuizCreate['quiz_type']>('assignment');
  const [timeLimit, setTimeLimit] = useState<string>('');
  const [shuffleAnswers, setShuffleAnswers] = useState(true);
  const [allowedAttempts, setAllowedAttempts] = useState(1);
  const [publishImmediately, setPublishImmediately] = useState(false);
  const [defaultPoints, setDefaultPoints] = useState(1);

  // ----- Question Banks (Step 2) -----
  const [banks, setBanks] = useState<AssessmentQuestionBank[]>([]);
  const [banksLoading, setBanksLoading] = useState(false);
  const [banksError, setBanksError] = useState<string | null>(null);

  // Expanded bank → show questions
  const [expandedBankId, setExpandedBankId] = useState<number | null>(null);
  const [bankQuestions, setBankQuestions] = useState<Record<number, AssessmentQuestion[]>>({});
  const [bankQuestionsLoading, setBankQuestionsLoading] = useState(false);

  // Search filter for banks
  const [bankSearch, setBankSearch] = useState('');

  // Manually selected questions per bank
  const [selectedQuestions, setSelectedQuestions] = useState<SelectedBankQuestions[]>([]);

  // Random question groups
  const [questionGroups, setQuestionGroups] = useState<QuestionGroupRow[]>([]);

  // ----- Creation state (Step 3) -----
  const [creating, setCreating] = useState(false);
  const [result, setResult] = useState<CreateCanvasQuizResponse | null>(null);
  const [error, setError] = useState<string | null>(null);

  // ----- Fetch courses on mount -----
  const fetchCourses = useCallback(async () => {
    setCoursesLoading(true);
    try {
      const res = await canvasApi.fetchCourses();
      if (res.success) setCourses(res.courses);
    } catch {
      /* ignore */
    } finally {
      setCoursesLoading(false);
    }
  }, []);

  useEffect(() => {
    fetchCourses();
  }, [fetchCourses]);

  // ----- Fetch banks when course is selected -----
  const fetchBanks = useCallback(async (courseId: number) => {
    setBanksLoading(true);
    setBanksError(null);
    try {
      const res = await canvasQuizApi.fetchQuestionBanks(courseId);
      if (res.success) {
        setBanks(res.banks);
      } else {
        setBanksError(res.error || 'Không thể tải question banks');
      }
    } catch {
      setBanksError('Lỗi kết nối');
    } finally {
      setBanksLoading(false);
    }
  }, []);

  useEffect(() => {
    if (selectedCourseId) {
      fetchBanks(selectedCourseId);
    }
  }, [selectedCourseId, fetchBanks]);

  // ----- Expand a bank to see questions -----
  const toggleBank = useCallback(
    async (bankId: number) => {
      if (expandedBankId === bankId) {
        setExpandedBankId(null);
        return;
      }
      setExpandedBankId(bankId);
      if (!bankQuestions[bankId] && selectedCourseId) {
        setBankQuestionsLoading(true);
        try {
          const res = await canvasQuizApi.fetchBankQuestions(selectedCourseId, bankId);
          if (res.success) {
            setBankQuestions((prev) => ({ ...prev, [bankId]: res.questions }));
          }
        } catch {
          /* ignore */
        } finally {
          setBankQuestionsLoading(false);
        }
      }
    },
    [expandedBankId, bankQuestions, selectedCourseId],
  );

  // ----- Toggle question selection -----
  const toggleQuestion = useCallback(
    (bankId: number, bankTitle: string, questionId: number) => {
      setSelectedQuestions((prev) => {
        const existing = prev.find((s) => s.bank_id === bankId);
        if (existing) {
          const has = existing.question_ids.includes(questionId);
          const newIds = has
            ? existing.question_ids.filter((id) => id !== questionId)
            : [...existing.question_ids, questionId];
          if (newIds.length === 0) return prev.filter((s) => s.bank_id !== bankId);
          return prev.map((s) =>
            s.bank_id === bankId ? { ...s, question_ids: newIds } : s,
          );
        }
        return [...prev, { bank_id: bankId, bank_title: bankTitle, question_ids: [questionId] }];
      });
    },
    [],
  );

  const isQuestionSelected = useCallback(
    (bankId: number, questionId: number) => {
      return (
        selectedQuestions
          .find((s) => s.bank_id === bankId)
          ?.question_ids.includes(questionId) ?? false
      );
    },
    [selectedQuestions],
  );

  // ----- Toggle all questions in a bank -----
  const toggleAllInBank = useCallback(
    (bankId: number, bankTitle: string) => {
      const qs = bankQuestions[bankId] || [];
      const existing = selectedQuestions.find((s) => s.bank_id === bankId);
      if (existing && existing.question_ids.length === qs.length) {
        // Deselect all
        setSelectedQuestions((prev) => prev.filter((s) => s.bank_id !== bankId));
      } else {
        // Select all
        setSelectedQuestions((prev) => {
          const rest = prev.filter((s) => s.bank_id !== bankId);
          return [...rest, { bank_id: bankId, bank_title: bankTitle, question_ids: qs.map((q) => q.id) }];
        });
      }
    },
    [bankQuestions, selectedQuestions],
  );

  // ----- Question Group management -----
  const addQuestionGroup = useCallback(
    (bankId: number, bankTitle: string) => {
      const bank = banks.find((b) => b.id === bankId);
      const maxPick = bank?.assessment_question_count || 5;
      setQuestionGroups((prev) => [
        ...prev,
        {
          id: `grp-${Date.now()}`,
          bank_id: bankId,
          bank_title: bankTitle,
          name: `Random — ${bankTitle}`,
          pick_count: Math.min(5, maxPick),
          question_points: defaultPoints,
        },
      ]);
    },
    [banks, defaultPoints],
  );

  const removeQuestionGroup = useCallback((id: string) => {
    setQuestionGroups((prev) => prev.filter((g) => g.id !== id));
  }, []);

  const updateGroupField = useCallback(
    (id: string, field: keyof QuestionGroupRow, value: string | number) => {
      setQuestionGroups((prev) =>
        prev.map((g) => (g.id === id ? { ...g, [field]: value } : g)),
      );
    },
    [],
  );

  // ----- Filtered banks -----
  const filteredBanks = useMemo(() => {
    if (!bankSearch.trim()) return banks;
    const q = bankSearch.toLowerCase();
    return banks.filter((b) => b.title?.toLowerCase().includes(q));
  }, [banks, bankSearch]);

  // ----- Summary counts -----
  const totalSelectedQuestions = useMemo(
    () => selectedQuestions.reduce((s, b) => s + b.question_ids.length, 0),
    [selectedQuestions],
  );
  const totalGroupPicks = useMemo(
    () => questionGroups.reduce((s, g) => s + g.pick_count, 0),
    [questionGroups],
  );

  // ----- Validation -----
  const step1Valid = !!quizTitle.trim() && !!selectedCourseId;
  const step2Valid = totalSelectedQuestions > 0 || questionGroups.length > 0;

  // ----- CREATE QUIZ -----
  const handleCreate = useCallback(async () => {
    if (!selectedCourseId) return;
    setCreating(true);
    setError(null);
    setResult(null);

    const quizParams: CanvasQuizCreate = {
      title: quizTitle,
      description: quizDescription || undefined,
      quiz_type: quizType,
      time_limit: timeLimit ? parseInt(timeLimit, 10) : undefined,
      shuffle_answers: shuffleAnswers,
      allowed_attempts: allowedAttempts,
      published: publishImmediately,
    };

    const bankQs: BankQuestionSelect[] = selectedQuestions.map((s) => ({
      bank_id: s.bank_id,
      question_ids: s.question_ids,
    }));

    const groups: QuestionGroupConfig[] = questionGroups.map((g) => ({
      bank_id: g.bank_id,
      name: g.name,
      pick_count: g.pick_count,
      question_points: g.question_points,
    }));

    try {
      const res = await canvasQuizApi.createFullQuiz({
        course_id: selectedCourseId,
        quiz: quizParams,
        bank_questions: bankQs,
        question_groups: groups,
        default_points: defaultPoints,
      });
      if (res.success) {
        setResult(res);
      } else {
        setError(res.error || 'Tạo quiz thất bại');
      }
    } catch {
      setError('Lỗi kết nối server');
    } finally {
      setCreating(false);
    }
  }, [
    selectedCourseId, quizTitle, quizDescription, quizType,
    timeLimit, shuffleAnswers, allowedAttempts, publishImmediately,
    selectedQuestions, questionGroups, defaultPoints,
  ]);

  // ----- Reset wizard -----
  const resetWizard = useCallback(() => {
    setStep(1);
    setQuizTitle('');
    setQuizDescription('');
    setQuizType('assignment');
    setTimeLimit('');
    setShuffleAnswers(true);
    setAllowedAttempts(1);
    setPublishImmediately(false);
    setSelectedQuestions([]);
    setQuestionGroups([]);
    setResult(null);
    setError(null);
  }, []);

  // ================================================================
  // RENDER
  // ================================================================

  return (
    <>
      <style>{panelCss}</style>
      <div className="cqp-root">
        {/* BG decorations */}
        <div className="cqp-bg-decoration">
          <div className="cqp-bg-orb cqp-bg-orb-1" />
          <div className="cqp-bg-orb cqp-bg-orb-2" />
          <div className="cqp-bg-orb cqp-bg-orb-3" />
        </div>
        <div className="cqp-stars">
          {STARS.map((s) => (
            <div
              key={s.id}
              className="cqp-star"
              style={
                {
                  top: s.top,
                  left: s.left,
                  width: s.size,
                  height: s.size,
                  '--duration': s.duration,
                  '--delay': s.delay,
                } as React.CSSProperties
              }
            />
          ))}
        </div>
        <div className="cqp-glow-line cqp-glow-line-1" />
        <div className="cqp-glow-line cqp-glow-line-2" />

        {/* ===== Hero Header ===== */}
        <div className="cqp-hero-header">
          <div className="cqp-hero-icon">
            <PenSquare size={26} />
          </div>
          <div className="cqp-hero-text">
            <h2>Canvas Quiz Builder</h2>
            <p>Tạo quiz trên Canvas từ Question Bank</p>
          </div>
          <PanelHelpButton panelKey="canvas_quiz" />
          <button className="cqp-btn-hero-refresh" onClick={resetWizard} title="Tạo quiz mới">
            <RefreshCw size={18} />
          </button>
        </div>

        {/* ===== Step Indicator ===== */}
        <div className="cqp-stepper">
          {[1, 2, 3].map((s) => (
            <React.Fragment key={s}>
              <div
                className={`cqp-step-dot ${step >= s ? 'active' : ''} ${step === s ? 'current' : ''}`}
                onClick={() => {
                  if (s === 1) setStep(1);
                  else if (s === 2 && step1Valid) setStep(2);
                  else if (s === 3 && step1Valid && step2Valid) setStep(3);
                }}
              >
                {step > s ? <CheckCircle size={16} /> : s}
              </div>
              {s < 3 && <div className={`cqp-step-line ${step > s ? 'filled' : ''}`} />}
            </React.Fragment>
          ))}
          <div className="cqp-step-labels">
            <span className={step === 1 ? 'active' : ''}>Cài đặt</span>
            <span className={step === 2 ? 'active' : ''}>Chọn câu hỏi</span>
            <span className={step === 3 ? 'active' : ''}>Xác nhận</span>
          </div>
        </div>

        {/* ===== Content ===== */}
        <div className="cqp-content">
          {/* ---------- STEP 1: Settings ---------- */}
          {step === 1 && (
            <div className="cqp-step-panel">
              {/* Course selector */}
              <div className="cqp-card">
                <h3 className="cqp-card-title"><BookOpen size={18} /> Chọn khóa học</h3>
                {coursesLoading ? (
                  <div className="cqp-loading"><Loader2 className="spin" size={20} /> Đang tải khóa học…</div>
                ) : (
                  <select
                    className="cqp-select"
                    value={selectedCourseId ?? ''}
                    onChange={(e) => {
                      const id = Number(e.target.value);
                      setSelectedCourseId(id || null);
                      const c = courses.find((c) => c.id === id);
                      setSelectedCourseName(c?.name ?? '');
                    }}
                  >
                    <option value="">— Chọn khóa học —</option>
                    {courses.map((c) => (
                      <option key={c.id} value={c.id}>{c.name} ({c.course_code})</option>
                    ))}
                  </select>
                )}
              </div>

              {/* Quiz settings */}
              <div className="cqp-card">
                <h3 className="cqp-card-title"><PenSquare size={18} /> Thiết lập Quiz</h3>

                <label className="cqp-label">Tên quiz <span className="required">*</span></label>
                <input
                  className="cqp-input"
                  placeholder="Ví dụ: Kiểm tra giữa kỳ"
                  value={quizTitle}
                  onChange={(e) => setQuizTitle(e.target.value)}
                />

                <label className="cqp-label">Mô tả</label>
                <textarea
                  className="cqp-input cqp-textarea"
                  placeholder="Mô tả quiz (hỗ trợ HTML)"
                  value={quizDescription}
                  onChange={(e) => setQuizDescription(e.target.value)}
                  rows={3}
                />

                <div className="cqp-row">
                  <div className="cqp-field">
                    <label className="cqp-label">Loại quiz</label>
                    <select className="cqp-select" value={quizType} onChange={(e) => setQuizType(e.target.value as CanvasQuizCreate['quiz_type'])}>
                      <option value="assignment">Graded Quiz</option>
                      <option value="practice_quiz">Practice Quiz</option>
                      <option value="graded_survey">Graded Survey</option>
                      <option value="survey">Ungraded Survey</option>
                    </select>
                  </div>
                  <div className="cqp-field">
                    <label className="cqp-label">Thời gian (phút)</label>
                    <input
                      className="cqp-input"
                      type="number"
                      min={0}
                      placeholder="Không giới hạn"
                      value={timeLimit}
                      onChange={(e) => setTimeLimit(e.target.value)}
                    />
                  </div>
                </div>

                <div className="cqp-row">
                  <div className="cqp-field">
                    <label className="cqp-label">Số lần làm</label>
                    <input
                      className="cqp-input"
                      type="number"
                      min={-1}
                      value={allowedAttempts}
                      onChange={(e) => setAllowedAttempts(Number(e.target.value))}
                    />
                    <span className="cqp-hint">-1 = không giới hạn</span>
                  </div>
                  <div className="cqp-field">
                    <label className="cqp-label">Điểm mặc định / câu</label>
                    <input
                      className="cqp-input"
                      type="number"
                      min={0}
                      step={0.5}
                      value={defaultPoints}
                      onChange={(e) => setDefaultPoints(Number(e.target.value))}
                    />
                  </div>
                </div>

                <div className="cqp-toggles">
                  <label className="cqp-toggle-row" onClick={() => setShuffleAnswers(!shuffleAnswers)}>
                    <div className={`cqp-toggle-track ${shuffleAnswers ? 'on' : ''}`}>
                      <div className="cqp-toggle-thumb" />
                    </div>
                    <span>Trộn đáp án</span>
                  </label>
                  <label className="cqp-toggle-row" onClick={() => setPublishImmediately(!publishImmediately)}>
                    <div className={`cqp-toggle-track ${publishImmediately ? 'on' : ''}`}>
                      <div className="cqp-toggle-thumb" />
                    </div>
                    <span>Publish ngay</span>
                  </label>
                </div>
              </div>

              <div className="cqp-nav">
                <div />
                <button
                  className="cqp-btn-primary"
                  disabled={!step1Valid}
                  onClick={() => setStep(2)}
                >
                  Tiếp theo <ChevronRight size={18} />
                </button>
              </div>
            </div>
          )}

          {/* ---------- STEP 2: Select Questions ---------- */}
          {step === 2 && (
            <div className="cqp-step-panel">
              <div className="cqp-info-bar">
                <Info size={16} />
                <span>
                  Chọn câu hỏi thủ công từ bank <strong>(Chọn thủ công)</strong> hoặc tạo nhóm ngẫu nhiên <strong>(Nhóm ngẫu nhiên)</strong>.
                </span>
              </div>

              {/* Search */}
              <div className="cqp-search-bar">
                <Search size={16} />
                <input
                  placeholder="Tìm question bank…"
                  value={bankSearch}
                  onChange={(e) => setBankSearch(e.target.value)}
                />
                <button className="cqp-btn-icon-sm" onClick={() => selectedCourseId && fetchBanks(selectedCourseId)} title="Refresh">
                  <RefreshCw size={14} />
                </button>
              </div>

              {/* Bank list */}
              {banksLoading ? (
                <div className="cqp-loading"><Loader2 className="spin" size={20} /> Đang tải banks…</div>
              ) : banksError ? (
                <div className="cqp-error"><AlertCircle size={16} /> {banksError}</div>
              ) : filteredBanks.length === 0 ? (
                <div className="cqp-empty">
                  <Library size={32} />
                  <p>Không tìm thấy question bank nào.</p>
                  <span className="cqp-hint">Hãy import QTI để tạo bank trước.</span>
                </div>
              ) : (
                <div className="cqp-bank-list">
                  {filteredBanks.map((bank) => {
                    const isExpanded = expandedBankId === bank.id;
                    const qs = bankQuestions[bank.id] || [];
                    const selCount =
                      selectedQuestions.find((s) => s.bank_id === bank.id)?.question_ids.length ?? 0;
                    const groupCount = questionGroups.filter((g) => g.bank_id === bank.id).length;

                    return (
                      <div key={bank.id} className={`cqp-bank-card ${isExpanded ? 'expanded' : ''}`}>
                        {/* Bank header */}
                        <div className="cqp-bank-header" onClick={() => toggleBank(bank.id)}>
                          <div className="cqp-bank-info">
                            <Library size={18} />
                            <div>
                              <span className="cqp-bank-name">{bank.title}</span>
                              <span className="cqp-bank-count">
                                {bank.assessment_question_count ?? '?'} câu hỏi
                              </span>
                            </div>
                          </div>
                          <div className="cqp-bank-badges">
                            {selCount > 0 && (
                              <span className="cqp-badge manual">{selCount} đã chọn</span>
                            )}
                            {groupCount > 0 && (
                              <span className="cqp-badge random">{groupCount} nhóm</span>
                            )}
                            <button
                              className="cqp-btn-icon-sm add"
                              title="Thêm Random Group"
                              onClick={(e) => {
                                e.stopPropagation();
                                addQuestionGroup(bank.id, bank.title);
                              }}
                            >
                              <Shuffle size={14} />
                              <Plus size={10} className="cqp-plus-overlay" />
                            </button>
                            {isExpanded ? <ChevronUp size={18} /> : <ChevronDown size={18} />}
                          </div>
                        </div>

                        {/* Expanded: questions */}
                        {isExpanded && (
                          <div className="cqp-bank-body">
                            {bankQuestionsLoading && qs.length === 0 ? (
                              <div className="cqp-loading sm"><Loader2 className="spin" size={16} /> Đang tải câu hỏi…</div>
                            ) : qs.length === 0 ? (
                              <div className="cqp-empty sm">Không có câu hỏi</div>
                            ) : (
                              <>
                                <div className="cqp-bank-actions">
                                  <button
                                    className="cqp-btn-text"
                                    onClick={() => toggleAllInBank(bank.id, bank.title)}
                                  >
                                    {selCount === qs.length ? 'Bỏ chọn tất cả' : 'Chọn tất cả'}
                                  </button>
                                </div>
                                <div className="cqp-question-list">
                                  {qs.map((q) => (
                                    <label
                                      key={q.id}
                                      className={`cqp-question-row ${isQuestionSelected(bank.id, q.id) ? 'selected' : ''}`}
                                    >
                                      <input
                                        type="checkbox"
                                        checked={isQuestionSelected(bank.id, q.id)}
                                        onChange={() =>
                                          toggleQuestion(bank.id, bank.title, q.id)
                                        }
                                      />
                                      <div className="cqp-question-info">
                                        <span className="cqp-q-name">
                                          {q.question_name || `Question ${q.id}`}
                                        </span>
                                        <span
                                          className="cqp-q-text"
                                          dangerouslySetInnerHTML={{
                                            __html:
                                              (q.question_text || '').slice(0, 150) +
                                              ((q.question_text || '').length > 150 ? '…' : ''),
                                          }}
                                        />
                                      </div>
                                      <span className="cqp-q-type">{q.question_type?.replace(/_/g, ' ')}</span>
                                    </label>
                                  ))}
                                </div>
                              </>
                            )}
                          </div>
                        )}
                      </div>
                    );
                  })}
                </div>
              )}

              {/* Question Groups section */}
              {questionGroups.length > 0 && (
                <div className="cqp-card" style={{ marginTop: 16 }}>
                  <h3 className="cqp-card-title"><Shuffle size={18} /> Random Question Groups</h3>
                  <div className="cqp-group-list">
                    {questionGroups.map((g) => (
                      <div key={g.id} className="cqp-group-row">
                        <div className="cqp-group-info">
                          <span className="cqp-group-bank">{g.bank_title}</span>
                          <input
                            className="cqp-input sm"
                            value={g.name}
                            onChange={(e) => updateGroupField(g.id, 'name', e.target.value)}
                            placeholder="Group name"
                          />
                        </div>
                        <div className="cqp-group-fields">
                          <div className="cqp-mini-field">
                            <label>Pick</label>
                            <input
                              type="number"
                              min={1}
                              className="cqp-input xs"
                              value={g.pick_count}
                              onChange={(e) =>
                                updateGroupField(g.id, 'pick_count', Math.max(1, Number(e.target.value)))
                              }
                            />
                          </div>
                          <div className="cqp-mini-field">
                            <label>Điểm</label>
                            <input
                              type="number"
                              min={0}
                              step={0.5}
                              className="cqp-input xs"
                              value={g.question_points}
                              onChange={(e) =>
                                updateGroupField(g.id, 'question_points', Number(e.target.value))
                              }
                            />
                          </div>
                          <button className="cqp-btn-icon-sm danger" onClick={() => removeQuestionGroup(g.id)}>
                            <Trash2 size={14} />
                          </button>
                        </div>
                      </div>
                    ))}
                  </div>
                </div>
              )}

              {/* Summary bar */}
              <div className="cqp-summary-bar">
                <span>
                  <strong>{totalSelectedQuestions}</strong> câu hỏi thủ công
                  {' · '}
                  <strong>{questionGroups.length}</strong> random group ({totalGroupPicks} câu)
                </span>
              </div>

              <div className="cqp-nav">
                <button className="cqp-btn-secondary" onClick={() => setStep(1)}>
                  <ChevronLeft size={18} /> Quay lại
                </button>
                <button
                  className="cqp-btn-primary"
                  disabled={!step2Valid}
                  onClick={() => setStep(3)}
                >
                  Xác nhận <ChevronRight size={18} />
                </button>
              </div>
            </div>
          )}

          {/* ---------- STEP 3: Review & Create ---------- */}
          {step === 3 && !result && (
            <div className="cqp-step-panel">
              <div className="cqp-card review">
                <h3 className="cqp-card-title"><CheckCircle size={18} /> Xem lại & Tạo Quiz</h3>

                <div className="cqp-review-grid">
                  <div className="cqp-review-item">
                    <span className="cqp-review-label">Khóa học</span>
                    <span className="cqp-review-value">{selectedCourseName}</span>
                  </div>
                  <div className="cqp-review-item">
                    <span className="cqp-review-label">Tên quiz</span>
                    <span className="cqp-review-value">{quizTitle}</span>
                  </div>
                  <div className="cqp-review-item">
                    <span className="cqp-review-label">Loại</span>
                    <span className="cqp-review-value">{{ assignment: 'Bài kiểm tra', practice_quiz: 'Bài luyện tập', graded_survey: 'Khảo sát có điểm', survey: 'Khảo sát' }[quizType] || quizType}</span>
                  </div>
                  <div className="cqp-review-item">
                    <span className="cqp-review-label">Thời gian</span>
                    <span className="cqp-review-value">{timeLimit ? `${timeLimit} phút` : 'Không giới hạn'}</span>
                  </div>
                  <div className="cqp-review-item">
                    <span className="cqp-review-label">Trộn đáp án</span>
                    <span className="cqp-review-value">{shuffleAnswers ? 'Có' : 'Không'}</span>
                  </div>
                  <div className="cqp-review-item">
                    <span className="cqp-review-label">Publish</span>
                    <span className="cqp-review-value">{publishImmediately ? 'Ngay lập tức' : 'Bản nháp'}</span>
                  </div>
                </div>

                <div className="cqp-review-section">
                  <h4>Câu hỏi thủ công</h4>
                  {selectedQuestions.length === 0 ? (
                    <p className="cqp-muted">Không có</p>
                  ) : (
                    <ul className="cqp-review-list">
                      {selectedQuestions.map((s) => (
                        <li key={s.bank_id}>
                          <Library size={14} /> {s.bank_title}: <strong>{s.question_ids.length}</strong> câu
                        </li>
                      ))}
                    </ul>
                  )}
                </div>

                <div className="cqp-review-section">
                  <h4>Nhóm ngẫu nhiên</h4>
                  {questionGroups.length === 0 ? (
                    <p className="cqp-muted">Không có</p>
                  ) : (
                    <ul className="cqp-review-list">
                      {questionGroups.map((g) => (
                        <li key={g.id}>
                          <Shuffle size={14} /> {g.name}: pick <strong>{g.pick_count}</strong> câu
                          ({g.question_points} đ/câu) — từ {g.bank_title}
                        </li>
                      ))}
                    </ul>
                  )}
                </div>

                <div className="cqp-total-bar">
                  Tổng: ~<strong>{totalSelectedQuestions + totalGroupPicks}</strong> câu hỏi
                  {' · '}
                  ~<strong>{(totalSelectedQuestions * defaultPoints + questionGroups.reduce((s, g) => s + g.pick_count * g.question_points, 0)).toFixed(1)}</strong> điểm
                </div>
              </div>

              {error && (
                <div className="cqp-error"><AlertCircle size={16} /> {error}</div>
              )}

              <div className="cqp-nav">
                <button className="cqp-btn-secondary" onClick={() => setStep(2)}>
                  <ChevronLeft size={18} /> Quay lại
                </button>
                <button
                  className="cqp-btn-primary create"
                  disabled={creating}
                  onClick={handleCreate}
                >
                  {creating ? (
                    <>
                      <Loader2 className="spin" size={18} /> Đang tạo…
                    </>
                  ) : (
                    <>
                      <PenSquare size={18} /> Tạo Quiz trên Canvas
                    </>
                  )}
                </button>
              </div>
            </div>
          )}

          {/* ---------- SUCCESS RESULT ---------- */}
          {step === 3 && result && (
            <div className="cqp-step-panel">
              <div className="cqp-result-card success">
                <CheckCircle size={48} className="cqp-result-icon" />
                <h3>Quiz đã được tạo thành công!</h3>
                <p className="cqp-result-msg">{result.message}</p>

                <div className="cqp-result-details">
                  <span>Câu hỏi: <strong>{result.questions_added}</strong></span>
                  <span>Nhóm: <strong>{result.groups_created}</strong></span>
                </div>

                {result.quiz_url && (
                  <a
                    className="cqp-btn-primary"
                    href={result.quiz_url}
                    target="_blank"
                    rel="noopener noreferrer"
                  >
                    <ExternalLink size={16} /> Mở Quiz trên Canvas
                  </a>
                )}

                <button className="cqp-btn-secondary" style={{ marginTop: 12 }} onClick={resetWizard}>
                  <RefreshCw size={16} /> Tạo quiz mới
                </button>
              </div>
            </div>
          )}
        </div>
      </div>
    </>
  );
};

export default CanvasQuizPanel;

// ============================================================================
// Embedded CSS (follows DocumentRAGPanel pattern)
// ============================================================================

const panelCss = `
/* ===== Root ===== */
.cqp-root {
  position: relative;
  height: 100%;
  overflow: hidden;
  background: #080b18;
  display: flex;
  flex-direction: column;
}

/* ===== BG Decorations ===== */
.cqp-root::before {
  content: '';
  position: absolute;
  inset: 0;
  background:
    radial-gradient(ellipse 80% 60% at 20% 10%, rgba(56, 189, 248, 0.10) 0%, transparent 60%),
    radial-gradient(ellipse 60% 50% at 80% 90%, rgba(139, 92, 246, 0.08) 0%, transparent 60%),
    radial-gradient(ellipse 50% 40% at 50% 50%, rgba(6, 182, 212, 0.05) 0%, transparent 60%);
  pointer-events: none;
  z-index: 0;
}
.cqp-root::after {
  content: '';
  position: absolute;
  inset: 0;
  background-image:
    linear-gradient(rgba(56, 189, 248, 0.02) 1px, transparent 1px),
    linear-gradient(90deg, rgba(56, 189, 248, 0.02) 1px, transparent 1px);
  background-size: 50px 50px;
  mask-image: radial-gradient(ellipse 80% 70% at 50% 50%, black 20%, transparent 75%);
  -webkit-mask-image: radial-gradient(ellipse 80% 70% at 50% 50%, black 20%, transparent 75%);
  animation: cqp-grid-drift 30s linear infinite;
  pointer-events: none;
  z-index: 0;
}
@keyframes cqp-grid-drift {
  from { transform: translate(0, 0); }
  to { transform: translate(50px, 50px); }
}
.cqp-root > * { position: relative; z-index: 1; }

/* Orbs */
.cqp-bg-decoration { position: absolute; inset: 0; pointer-events: none; z-index: 0; overflow: hidden; }
.cqp-bg-orb {
  position: absolute;
  border-radius: 50%;
  filter: blur(70px);
  pointer-events: none;
}
.cqp-bg-orb-1 {
  width: 350px; height: 350px;
  top: -5%; right: -8%;
  background: radial-gradient(circle, rgba(56, 189, 248, 0.13) 0%, transparent 70%);
  animation: cqp-float1 22s ease-in-out infinite;
}
.cqp-bg-orb-2 {
  width: 300px; height: 300px;
  bottom: 10%; left: -10%;
  background: radial-gradient(circle, rgba(139, 92, 246, 0.10) 0%, transparent 70%);
  animation: cqp-float2 26s ease-in-out infinite;
}
.cqp-bg-orb-3 {
  width: 220px; height: 220px;
  top: 40%; right: 15%;
  background: radial-gradient(circle, rgba(34, 211, 238, 0.07) 0%, transparent 70%);
  animation: cqp-float3 18s ease-in-out infinite;
}
@keyframes cqp-float1 {
  0%, 100% { transform: translate(0, 0) scale(1); }
  33% { transform: translate(-20px, 15px) scale(1.05); }
  66% { transform: translate(10px, -10px) scale(0.97); }
}
@keyframes cqp-float2 {
  0%, 100% { transform: translate(0, 0) scale(1); }
  33% { transform: translate(15px, -20px) scale(1.03); }
  66% { transform: translate(-10px, 10px) scale(0.98); }
}
@keyframes cqp-float3 {
  0%, 100% { transform: translate(0, 0) scale(1); }
  50% { transform: translate(-15px, 15px) scale(1.08); }
}

/* Stars */
.cqp-stars { position: absolute; inset: 0; z-index: 0; pointer-events: none; overflow: hidden; }
.cqp-star {
  position: absolute;
  background: #ffffff;
  border-radius: 50%;
  box-shadow: 0 0 6px 1px rgba(255, 255, 255, 0.35);
  opacity: 0;
  animation: cqp-twinkle var(--duration, 4s) ease-in-out var(--delay, 0s) infinite;
}
@keyframes cqp-twinkle {
  0%, 100% { opacity: 0; transform: scale(0.5); }
  50% { opacity: 0.85; transform: scale(1.3); }
}

/* Glow lines */
.cqp-glow-line {
  position: absolute;
  height: 1px;
  pointer-events: none;
  z-index: 0;
}
.cqp-glow-line-1 {
  top: 18%;
  left: 0;
  width: 45%;
  background: linear-gradient(90deg, transparent, rgba(56, 189, 248, 0.30), transparent);
  animation: cqp-glow-slide 8s ease-in-out infinite;
}
.cqp-glow-line-2 {
  bottom: 25%;
  right: 0;
  width: 38%;
  background: linear-gradient(90deg, transparent, rgba(167, 139, 250, 0.22), transparent);
  animation: cqp-glow-slide 10s ease-in-out infinite reverse;
}
@keyframes cqp-glow-slide {
  0%, 100% { transform: translateX(-20px); opacity: 0.3; }
  50% { transform: translateX(20px); opacity: 1; }
}

/* ===== Hero Header ===== */
.cqp-hero-header {
  display: flex;
  align-items: center;
  gap: 16px;
  padding: 20px 28px;
  background: rgba(15, 23, 42, 0.85);
  backdrop-filter: blur(16px);
  -webkit-backdrop-filter: blur(16px);
  border-bottom: 1px solid rgba(56, 189, 248, 0.2);
  flex-shrink: 0;
  position: relative;
  z-index: 3;
  box-shadow: 0 4px 20px rgba(0, 0, 0, 0.3), inset 0 1px 0 rgba(255, 255, 255, 0.05);
}
.cqp-hero-header::after {
  content: '';
  position: absolute;
  bottom: -1px;
  left: 5%;
  width: 90%;
  height: 1px;
  background: linear-gradient(90deg, transparent, rgba(56, 189, 248, 0.4), rgba(139, 92, 246, 0.3), rgba(34, 211, 238, 0.2), transparent);
}
.cqp-hero-icon {
  position: relative;
  width: 48px;
  height: 48px;
  display: flex;
  align-items: center;
  justify-content: center;
  border-radius: 14px;
  background: linear-gradient(135deg, #38bdf8, #0ea5e9);
  color: white;
  box-shadow: 0 6px 20px -4px rgba(56, 189, 248, 0.5);
  flex-shrink: 0;
}
.cqp-hero-icon::before {
  content: '';
  position: absolute;
  inset: -4px;
  border-radius: 18px;
  border: 1.5px dashed rgba(56, 189, 248, 0.35);
  animation: cqp-icon-orbit 12s linear infinite;
}
@keyframes cqp-icon-orbit {
  from { transform: rotate(0deg); }
  to { transform: rotate(360deg); }
}
.cqp-hero-text h2 {
  font-weight: 700;
  font-size: 1.3rem;
  margin: 0;
  background: linear-gradient(135deg, #e0f2fe 0%, #bae6fd 40%, #7dd3fc 80%, #38bdf8 100%);
  -webkit-background-clip: text;
  -webkit-text-fill-color: transparent;
  background-clip: text;
}
.cqp-hero-text p {
  margin: 4px 0 0 0;
  font-size: 0.85rem;
  color: #94a3b8;
}
.cqp-btn-hero-refresh {
  margin-left: auto;
  width: 40px; height: 40px;
  display: flex; align-items: center; justify-content: center;
  border-radius: 10px;
  background: rgba(15, 23, 42, 0.6);
  border: 1px solid rgba(56, 189, 248, 0.2);
  color: #38bdf8;
  cursor: pointer;
  transition: all 0.3s;
}
.cqp-btn-hero-refresh:hover {
  background: rgba(56, 189, 248, 0.15);
  transform: rotate(180deg);
}

/* ===== Stepper ===== */
.cqp-stepper {
  display: flex;
  align-items: center;
  gap: 0;
  padding: 18px 28px 8px;
  position: relative;
  z-index: 3;
  flex-wrap: wrap;
}
.cqp-step-dot {
  width: 32px; height: 32px;
  border-radius: 50%;
  display: flex; align-items: center; justify-content: center;
  font-size: 0.8rem; font-weight: 700;
  background: rgba(30, 41, 59, 0.8);
  border: 2px solid rgba(100, 116, 139, 0.3);
  color: #64748b;
  cursor: pointer;
  transition: all 0.3s;
  flex-shrink: 0;
}
.cqp-step-dot.active {
  border-color: #38bdf8;
  color: #38bdf8;
}
.cqp-step-dot.current {
  background: linear-gradient(135deg, rgba(56, 189, 248, 0.25), rgba(139, 92, 246, 0.2));
  box-shadow: 0 0 12px rgba(56, 189, 248, 0.25);
}
.cqp-step-line {
  flex: 1;
  height: 2px;
  background: rgba(100, 116, 139, 0.2);
  margin: 0 6px;
  border-radius: 1px;
  transition: background 0.3s;
  min-width: 40px;
}
.cqp-step-line.filled { background: rgba(56, 189, 248, 0.5); }
.cqp-step-labels {
  width: 100%;
  display: flex;
  justify-content: space-between;
  padding: 6px 8px 0;
}
.cqp-step-labels span {
  font-size: 0.72rem;
  color: #475569;
  transition: color 0.3s;
}
.cqp-step-labels span.active { color: #38bdf8; font-weight: 600; }

/* ===== Content ===== */
.cqp-content {
  flex: 1;
  overflow-y: auto;
  padding: 24px;
  display: flex;
  flex-direction: column;
  gap: 20px;
  position: relative;
  z-index: 3;
}
.cqp-content::-webkit-scrollbar { width: 8px; }
.cqp-content::-webkit-scrollbar-track { background: transparent; }
.cqp-content::-webkit-scrollbar-thumb {
  background: rgba(56, 189, 248, 0.2);
  border-radius: 10px;
}
.cqp-content::-webkit-scrollbar-thumb:hover { background: rgba(56, 189, 248, 0.35); }

/* ===== Cards ===== */
.cqp-card {
  background: rgba(22, 33, 55, 0.8);
  border: 1px solid rgba(56, 189, 248, 0.2);
  border-radius: 16px;
  padding: 24px;
  backdrop-filter: blur(12px);
  box-shadow: 0 4px 24px rgba(0, 0, 0, 0.35), inset 0 1px 0 rgba(255, 255, 255, 0.05), 0 0 0 1px rgba(56, 189, 248, 0.06);
  transition: border-color 0.3s ease, box-shadow 0.3s ease;
}
.cqp-card:hover {
  border-color: rgba(56, 189, 248, 0.35);
  box-shadow: 0 8px 32px rgba(56, 189, 248, 0.12), inset 0 1px 0 rgba(255, 255, 255, 0.06), 0 0 0 1px rgba(56, 189, 248, 0.1);
}
.cqp-card.review { border-color: rgba(56, 189, 248, 0.25); }
.cqp-card-title {
  display: flex;
  align-items: center;
  gap: 8px;
  font-size: 0.95rem;
  font-weight: 600;
  color: #e2e8f0;
  margin: 0 0 14px;
}
.cqp-card-title svg { color: #38bdf8; flex-shrink: 0; }

/* ===== Form Elements ===== */
.cqp-label {
  display: block;
  font-size: 0.82rem;
  color: #94a3b8;
  margin: 12px 0 4px;
  font-weight: 500;
}
.cqp-label .required { color: #ef4444; margin-left: 2px; }
.cqp-input {
  width: 100%;
  padding: 10px 14px;
  background: rgba(15, 23, 42, 0.6);
  border: 1px solid rgba(100, 116, 139, 0.25);
  border-radius: 10px;
  color: #e2e8f0;
  font-size: 0.88rem;
  outline: none;
  transition: border-color 0.2s;
  box-sizing: border-box;
}
.cqp-input:focus { border-color: rgba(56, 189, 248, 0.5); }
.cqp-input.sm { padding: 6px 10px; font-size: 0.82rem; }
.cqp-input.xs { width: 70px; padding: 5px 8px; font-size: 0.82rem; text-align: center; }
.cqp-textarea { resize: vertical; min-height: 60px; font-family: inherit; }
.cqp-select {
  width: 100%;
  padding: 10px 14px;
  background: rgba(15, 23, 42, 0.6);
  border: 1px solid rgba(100, 116, 139, 0.25);
  border-radius: 10px;
  color: #e2e8f0;
  font-size: 0.88rem;
  outline: none;
  cursor: pointer;
  appearance: none;
  background-image: url("data:image/svg+xml,%3Csvg xmlns='http://www.w3.org/2000/svg' width='12' height='12' fill='%2394a3b8' viewBox='0 0 16 16'%3E%3Cpath d='M8 11L3 6h10z'/%3E%3C/svg%3E");
  background-repeat: no-repeat;
  background-position: right 12px center;
}
.cqp-select:focus { border-color: rgba(56, 189, 248, 0.5); }
.cqp-select option { background: #1e293b; color: #e2e8f0; }
.cqp-hint {
  font-size: 0.72rem;
  color: #475569;
  display: block;
  margin-top: 2px;
}
.cqp-row {
  display: flex;
  gap: 16px;
}
.cqp-field { flex: 1; }

/* Toggles */
.cqp-toggles {
  display: flex;
  gap: 20px;
  margin-top: 16px;
  flex-wrap: wrap;
}
.cqp-toggle-row {
  display: flex;
  align-items: center;
  gap: 10px;
  cursor: pointer;
  font-size: 0.85rem;
  color: #94a3b8;
}
.cqp-toggle-track {
  width: 38px; height: 20px;
  border-radius: 10px;
  background: rgba(51, 65, 85, 0.7);
  position: relative;
  transition: background 0.3s;
  flex-shrink: 0;
}
.cqp-toggle-track.on {
  background: linear-gradient(135deg, #38bdf8, #0ea5e9);
}
.cqp-toggle-thumb {
  width: 14px; height: 14px;
  border-radius: 50%;
  background: white;
  position: absolute;
  top: 3px; left: 3px;
  transition: transform 0.3s;
}
.cqp-toggle-track.on .cqp-toggle-thumb { transform: translateX(18px); }

/* ===== Buttons ===== */
.cqp-btn-primary {
  display: inline-flex;
  align-items: center;
  gap: 8px;
  padding: 10px 22px;
  background: linear-gradient(135deg, #38bdf8, #0ea5e9);
  border: none;
  border-radius: 10px;
  color: white;
  font-weight: 600;
  font-size: 0.88rem;
  cursor: pointer;
  transition: all 0.3s;
  text-decoration: none;
}
.cqp-btn-primary:hover:not(:disabled) {
  box-shadow: 0 4px 16px rgba(56, 189, 248, 0.35);
  transform: translateY(-1px);
}
.cqp-btn-primary:disabled {
  opacity: 0.45;
  cursor: not-allowed;
}
.cqp-btn-primary.create {
  background: linear-gradient(135deg, #22c55e, #16a34a);
  padding: 12px 28px;
  font-size: 0.95rem;
}
.cqp-btn-primary.create:hover:not(:disabled) {
  box-shadow: 0 4px 16px rgba(34, 197, 94, 0.35);
}
.cqp-btn-secondary {
  display: inline-flex;
  align-items: center;
  gap: 8px;
  padding: 10px 22px;
  background: rgba(30, 41, 59, 0.7);
  border: 1px solid rgba(100, 116, 139, 0.3);
  border-radius: 10px;
  color: #94a3b8;
  font-weight: 500;
  font-size: 0.88rem;
  cursor: pointer;
  transition: all 0.2s;
}
.cqp-btn-secondary:hover {
  background: rgba(51, 65, 85, 0.6);
  color: #e2e8f0;
}
.cqp-btn-text {
  background: none;
  border: none;
  color: #38bdf8;
  font-size: 0.8rem;
  cursor: pointer;
  font-weight: 500;
  padding: 4px 8px;
  border-radius: 6px;
  transition: background 0.2s;
}
.cqp-btn-text:hover { background: rgba(56, 189, 248, 0.1); }
.cqp-btn-icon-sm {
  width: 30px; height: 30px;
  display: flex; align-items: center; justify-content: center;
  border-radius: 8px;
  background: rgba(30, 41, 59, 0.6);
  border: 1px solid rgba(100, 116, 139, 0.2);
  color: #94a3b8;
  cursor: pointer;
  transition: all 0.2s;
  flex-shrink: 0;
  position: relative;
}
.cqp-btn-icon-sm:hover { background: rgba(56, 189, 248, 0.15); color: #38bdf8; }
.cqp-btn-icon-sm.add { color: #38bdf8; border-color: rgba(56, 189, 248, 0.2); }
.cqp-btn-icon-sm.add:hover { background: rgba(56, 189, 248, 0.2); }
.cqp-btn-icon-sm.danger:hover { background: rgba(239, 68, 68, 0.15); color: #ef4444; border-color: rgba(239, 68, 68, 0.3); }
.cqp-plus-overlay {
  position: absolute;
  bottom: 2px; right: 2px;
}

/* ===== Nav bar ===== */
.cqp-nav {
  display: flex;
  justify-content: space-between;
  align-items: center;
  margin-top: 20px;
  padding-top: 16px;
  border-top: 1px solid rgba(100, 116, 139, 0.12);
}

/* ===== Info / Error / Loading ===== */
.cqp-loading {
  display: flex; align-items: center; gap: 10px;
  color: #64748b; font-size: 0.85rem;
  padding: 16px;
  justify-content: center;
}
.cqp-loading.sm { padding: 10px; font-size: 0.8rem; }
.cqp-error {
  display: flex; align-items: center; gap: 8px;
  color: #f87171; font-size: 0.85rem;
  padding: 12px 16px;
  background: rgba(239, 68, 68, 0.08);
  border: 1px solid rgba(239, 68, 68, 0.2);
  border-radius: 10px;
  margin-bottom: 12px;
}
.cqp-empty {
  display: flex;
  flex-direction: column;
  align-items: center;
  gap: 8px;
  padding: 32px;
  color: #475569;
  text-align: center;
}
.cqp-empty.sm { padding: 16px; font-size: 0.82rem; }
.cqp-empty svg { opacity: 0.4; }
.cqp-info-bar {
  display: flex;
  align-items: center;
  gap: 8px;
  padding: 10px 14px;
  background: rgba(56, 189, 248, 0.06);
  border: 1px solid rgba(56, 189, 248, 0.15);
  border-radius: 10px;
  font-size: 0.82rem;
  color: #94a3b8;
  margin-bottom: 14px;
}
.cqp-info-bar svg { color: #38bdf8; flex-shrink: 0; }

/* ===== Search ===== */
.cqp-search-bar {
  display: flex;
  align-items: center;
  gap: 8px;
  padding: 8px 14px;
  background: rgba(15, 23, 42, 0.5);
  border: 1px solid rgba(100, 116, 139, 0.2);
  border-radius: 10px;
  margin-bottom: 14px;
}
.cqp-search-bar svg { color: #475569; flex-shrink: 0; }
.cqp-search-bar input {
  flex: 1;
  background: none;
  border: none;
  color: #e2e8f0;
  font-size: 0.85rem;
  outline: none;
}
.cqp-search-bar input::placeholder { color: #475569; }

/* ===== Bank List ===== */
.cqp-bank-list {
  display: flex;
  flex-direction: column;
  gap: 10px;
}
.cqp-bank-card {
  background: rgba(22, 33, 55, 0.6);
  border: 1px solid rgba(100, 116, 139, 0.15);
  border-radius: 12px;
  overflow: hidden;
  transition: border-color 0.3s;
}
.cqp-bank-card.expanded { border-color: rgba(56, 189, 248, 0.25); }
.cqp-bank-header {
  display: flex;
  align-items: center;
  justify-content: space-between;
  padding: 14px 16px;
  cursor: pointer;
  transition: background 0.2s;
}
.cqp-bank-header:hover { background: rgba(56, 189, 248, 0.04); }
.cqp-bank-info {
  display: flex;
  align-items: center;
  gap: 12px;
}
.cqp-bank-info svg { color: #38bdf8; flex-shrink: 0; }
.cqp-bank-name {
  font-size: 0.9rem;
  font-weight: 600;
  color: #e2e8f0;
  display: block;
}
.cqp-bank-count {
  font-size: 0.75rem;
  color: #64748b;
  display: block;
}
.cqp-bank-badges {
  display: flex;
  align-items: center;
  gap: 8px;
}
.cqp-badge {
  padding: 2px 10px;
  border-radius: 12px;
  font-size: 0.7rem;
  font-weight: 600;
}
.cqp-badge.manual {
  background: rgba(56, 189, 248, 0.15);
  color: #38bdf8;
}
.cqp-badge.random {
  background: rgba(139, 92, 246, 0.15);
  color: #a78bfa;
}

/* Bank body */
.cqp-bank-body {
  border-top: 1px solid rgba(100, 116, 139, 0.1);
  padding: 12px 16px;
}
.cqp-bank-actions {
  display: flex;
  justify-content: flex-end;
  margin-bottom: 8px;
}

/* Question list */
.cqp-question-list {
  display: flex;
  flex-direction: column;
  gap: 4px;
  max-height: 320px;
  overflow-y: auto;
}
.cqp-question-list::-webkit-scrollbar { width: 4px; }
.cqp-question-list::-webkit-scrollbar-thumb { background: rgba(56, 189, 248, 0.15); border-radius: 2px; }
.cqp-question-row {
  display: flex;
  align-items: flex-start;
  gap: 10px;
  padding: 8px 10px;
  border-radius: 8px;
  cursor: pointer;
  transition: background 0.15s;
}
.cqp-question-row:hover { background: rgba(56, 189, 248, 0.05); }
.cqp-question-row.selected { background: rgba(56, 189, 248, 0.08); }
.cqp-question-row input[type="checkbox"] {
  margin-top: 3px;
  accent-color: #38bdf8;
  flex-shrink: 0;
  width: 16px; height: 16px;
  cursor: pointer;
}
.cqp-question-info { flex: 1; min-width: 0; }
.cqp-q-name {
  display: block;
  font-size: 0.84rem;
  font-weight: 600;
  color: #cbd5e1;
  white-space: nowrap;
  overflow: hidden;
  text-overflow: ellipsis;
}
.cqp-q-text {
  display: block;
  font-size: 0.76rem;
  color: #64748b;
  line-height: 1.35;
  margin-top: 2px;
  overflow: hidden;
  text-overflow: ellipsis;
  white-space: nowrap;
}
.cqp-q-text * { font-size: inherit !important; color: inherit !important; margin: 0 !important; padding: 0 !important; }
.cqp-q-type {
  font-size: 0.68rem;
  color: #475569;
  white-space: nowrap;
  flex-shrink: 0;
  margin-top: 4px;
}

/* ===== Question Groups ===== */
.cqp-group-list {
  display: flex;
  flex-direction: column;
  gap: 10px;
}
.cqp-group-row {
  display: flex;
  align-items: center;
  gap: 12px;
  padding: 12px 14px;
  background: rgba(15, 23, 42, 0.4);
  border: 1px solid rgba(139, 92, 246, 0.15);
  border-radius: 10px;
  flex-wrap: wrap;
}
.cqp-group-info {
  flex: 1;
  min-width: 160px;
}
.cqp-group-bank {
  font-size: 0.72rem;
  color: #a78bfa;
  display: block;
  margin-bottom: 4px;
}
.cqp-group-fields {
  display: flex;
  align-items: center;
  gap: 10px;
}
.cqp-mini-field {
  display: flex;
  flex-direction: column;
  gap: 2px;
}
.cqp-mini-field label {
  font-size: 0.68rem;
  color: #475569;
}

/* ===== Summary Bar ===== */
.cqp-summary-bar {
  padding: 10px 16px;
  background: rgba(22, 33, 55, 0.5);
  border: 1px solid rgba(56, 189, 248, 0.1);
  border-radius: 10px;
  font-size: 0.82rem;
  color: #94a3b8;
  margin-top: 14px;
  text-align: center;
}
.cqp-summary-bar strong { color: #38bdf8; }

/* ===== Review (Step 3) ===== */
.cqp-review-grid {
  display: grid;
  grid-template-columns: 1fr 1fr;
  gap: 10px;
  margin-bottom: 16px;
}
.cqp-review-item {
  padding: 10px 14px;
  background: rgba(15, 23, 42, 0.4);
  border-radius: 8px;
}
.cqp-review-label {
  display: block;
  font-size: 0.72rem;
  color: #64748b;
  margin-bottom: 2px;
}
.cqp-review-value {
  font-size: 0.88rem;
  color: #e2e8f0;
  font-weight: 500;
}
.cqp-review-section {
  margin-bottom: 14px;
}
.cqp-review-section h4 {
  font-size: 0.85rem;
  color: #94a3b8;
  margin: 0 0 8px;
  font-weight: 600;
}
.cqp-review-list {
  list-style: none;
  padding: 0;
  margin: 0;
  display: flex;
  flex-direction: column;
  gap: 6px;
}
.cqp-review-list li {
  display: flex;
  align-items: center;
  gap: 8px;
  padding: 8px 12px;
  background: rgba(15, 23, 42, 0.3);
  border-radius: 8px;
  font-size: 0.82rem;
  color: #94a3b8;
}
.cqp-review-list li svg { color: #38bdf8; flex-shrink: 0; }
.cqp-muted { color: #475569; font-size: 0.82rem; margin: 0; }
.cqp-total-bar {
  padding: 12px;
  background: linear-gradient(135deg, rgba(56, 189, 248, 0.08), rgba(139, 92, 246, 0.06));
  border: 1px solid rgba(56, 189, 248, 0.15);
  border-radius: 10px;
  text-align: center;
  font-size: 0.9rem;
  color: #e2e8f0;
}
.cqp-total-bar strong { color: #38bdf8; }

/* ===== Result Card ===== */
.cqp-result-card {
  text-align: center;
  padding: 40px 24px;
  background: rgba(22, 33, 55, 0.7);
  border-radius: 16px;
  border: 1px solid rgba(56, 189, 248, 0.12);
}
.cqp-result-card.success {
  border-color: rgba(34, 197, 94, 0.3);
}
.cqp-result-icon {
  color: #22c55e;
  margin-bottom: 16px;
}
.cqp-result-card h3 {
  font-size: 1.15rem;
  color: #e2e8f0;
  margin: 0 0 8px;
}
.cqp-result-msg {
  font-size: 0.88rem;
  color: #94a3b8;
  margin: 0 0 20px;
}
.cqp-result-details {
  display: flex;
  justify-content: center;
  gap: 20px;
  margin-bottom: 24px;
  font-size: 0.85rem;
  color: #94a3b8;
}
.cqp-result-details strong { color: #38bdf8; }

/* ===== Step panel animation ===== */
.cqp-step-panel {
  animation: cqp-fadeIn 0.3s ease-out;
}
@keyframes cqp-fadeIn {
  from { opacity: 0; transform: translateY(8px); }
  to { opacity: 1; transform: translateY(0); }
}
`;
