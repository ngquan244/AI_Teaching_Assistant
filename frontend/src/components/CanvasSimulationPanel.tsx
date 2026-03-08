import React, { useState, useEffect, useCallback } from 'react';
import {
  Play,
  Users,
  Plus,
  Trash2,
  Loader2,
  CheckCircle,
  AlertCircle,
  AlertTriangle,
  RefreshCw,
  BookOpen,
  ClipboardList,
  History,
  Shield,
} from 'lucide-react';
import PanelHelpButton from './PanelHelpButton';
import { canvasSimApi } from '../api/canvasSim';
import { canvasApi } from '../api/canvas';
import { canvasQuizApi } from '../api/canvasQuiz';
import type { CanvasCourse, CanvasQuiz } from '../types/canvas';
import type {
  TestStudent,
  PreCheckResponse,
  SimulationRunResult,
  SimulationAnswerItem,
  AuditLogEntry,
} from '../api/canvasSim';

// ============================================================================
// Decorative helpers
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

const STARS = makeStars(25);

// ============================================================================
// Sub-tabs
// ============================================================================

type SimTab = 'execute' | 'students' | 'history' | 'audit';

// ============================================================================
// Component
// ============================================================================

const CanvasSimulationPanel: React.FC = () => {
  const [activeTab, setActiveTab] = useState<SimTab>('execute');

  // Course + Quiz
  const [courses, setCourses] = useState<CanvasCourse[]>([]);
  const [coursesLoading, setCoursesLoading] = useState(false);
  const [selectedCourseId, setSelectedCourseId] = useState<number | null>(null);
  const [quizzes, setQuizzes] = useState<CanvasQuiz[]>([]);
  const [quizzesLoading, setQuizzesLoading] = useState(false);
  const [selectedQuizId, setSelectedQuizId] = useState<number | null>(null);

  // Pre-check
  const [preCheck, setPreCheck] = useState<PreCheckResponse | null>(null);
  const [preCheckLoading, setPreCheckLoading] = useState(false);

  // Test students
  const [students, setStudents] = useState<TestStudent[]>([]);
  const [studentsLoading, setStudentsLoading] = useState(false);
  const [studentError, setStudentError] = useState<string | null>(null);
  const [selectedStudentId, setSelectedStudentId] = useState<string | null>(null);
  const [newStudentName, setNewStudentName] = useState('');
  const [newStudentEmail, setNewStudentEmail] = useState('');
  const [creatingStudent, setCreatingStudent] = useState(false);

  // Execution
  const [accessCode, setAccessCode] = useState('');
  const [executing, setExecuting] = useState(false);
  const [execResult, setExecResult] = useState<Record<string, unknown> | null>(null);
  const [execError, setExecError] = useState<string | null>(null);

  // Questions for answer building
  const [questions, setQuestions] = useState<Array<Record<string, unknown>>>([]);
  const [questionsLoading, setQuestionsLoading] = useState(false);
  const [answers, setAnswers] = useState<Record<number, unknown>>({});

  // History
  const [history, setHistory] = useState<SimulationRunResult[]>([]);
  const [historyLoading, setHistoryLoading] = useState(false);

  // Audit
  const [auditLogs, setAuditLogs] = useState<AuditLogEntry[]>([]);
  const [auditLoading, setAuditLoading] = useState(false);

  // ---- Fetch courses ----
  const fetchCourses = useCallback(async () => {
    setCoursesLoading(true);
    try {
      const res = await canvasApi.fetchCourses();
      if (res.success) setCourses(res.courses);
    } catch { /* */ }
    finally { setCoursesLoading(false); }
  }, []);

  useEffect(() => { fetchCourses(); }, [fetchCourses]);

  // ---- Fetch quizzes when course changes ----
  useEffect(() => {
    if (!selectedCourseId) { setQuizzes([]); return; }
    let cancelled = false;
    (async () => {
      setQuizzesLoading(true);
      try {
        const res = await canvasQuizApi.fetchQuizzes(selectedCourseId);
        if (!cancelled && res.success) setQuizzes(res.quizzes);
      } catch { /* */ }
      finally { if (!cancelled) setQuizzesLoading(false); }
    })();
    return () => { cancelled = true; };
  }, [selectedCourseId]);

  // ---- Fetch test students ----
  const fetchStudents = useCallback(async () => {
    setStudentsLoading(true);
    setStudentError(null);
    try {
      const res = await canvasSimApi.listTestStudents();
      if (res.success) {
        setStudents(res.test_students);
      } else if (res.error) {
        setStudentError(res.error);
      }
    } catch { /* */ }
    finally { setStudentsLoading(false); }
  }, []);

  useEffect(() => { fetchStudents(); }, [fetchStudents]);

  // ---- Pre-check ----
  const runPreCheck = useCallback(async () => {
    if (!selectedCourseId || !selectedQuizId) return;
    setPreCheckLoading(true);
    try {
      const res = await canvasSimApi.preCheckQuiz(selectedCourseId, selectedQuizId);
      setPreCheck(res);
    } catch { /* */ }
    finally { setPreCheckLoading(false); }
  }, [selectedCourseId, selectedQuizId]);

  useEffect(() => {
    if (selectedCourseId && selectedQuizId) {
      runPreCheck();
      // Also fetch questions
      (async () => {
        setQuestionsLoading(true);
        try {
          const res = await canvasQuizApi.fetchQuizQuestions(selectedCourseId, selectedQuizId);
          if (res.success) setQuestions(res.questions);
        } catch { /* */ }
        finally { setQuestionsLoading(false); }
      })();
    } else {
      setPreCheck(null);
      setQuestions([]);
    }
  }, [selectedCourseId, selectedQuizId, runPreCheck]);

  // ---- Create test student ----
  const handleCreateStudent = async () => {
    if (!newStudentName || !newStudentEmail) return;
    setCreatingStudent(true);
    try {
      const res = await canvasSimApi.createTestStudent(newStudentName, newStudentEmail);
      if (res.success) {
        setNewStudentName('');
        setNewStudentEmail('');
        fetchStudents();
      } else {
        alert(res.error || 'Failed');
      }
    } catch { /* */ }
    finally { setCreatingStudent(false); }
  };

  // ---- Delete test student ----
  const handleDeleteStudent = async (id: string) => {
    if (!confirm('Xóa test student này?')) return;
    await canvasSimApi.deleteTestStudent(id);
    fetchStudents();
  };

  // ---- Set answer for a question ----
  const setAnswer = (questionId: number, value: unknown) => {
    setAnswers((prev) => ({ ...prev, [questionId]: value }));
  };

  // ---- Execute simulation ----
  const handleExecute = async () => {
    if (!selectedCourseId || !selectedQuizId || !selectedStudentId) return;
    setExecuting(true);
    setExecResult(null);
    setExecError(null);

    const answerList: SimulationAnswerItem[] = Object.entries(answers).map(([qid, ans]) => ({
      question_id: Number(qid),
      answer: ans,
    }));

    try {
      const res = await canvasSimApi.executeSimulation({
        course_id: selectedCourseId,
        quiz_id: selectedQuizId,
        test_student_id: selectedStudentId,
        answers: answerList,
        access_code: accessCode || undefined,
      });
      if (res.success) {
        setExecResult(res as unknown as Record<string, unknown>);
      } else {
        setExecError(res.error || 'Simulation failed');
      }
    } catch (e: unknown) {
      setExecError(String(e));
    } finally {
      setExecuting(false);
    }
  };

  // ---- History ----
  const fetchHistory = useCallback(async () => {
    setHistoryLoading(true);
    try {
      const res = await canvasSimApi.getSimulationHistory(
        selectedCourseId ?? undefined,
        selectedQuizId ?? undefined,
      );
      if (res.success) setHistory(res.runs);
    } catch { /* */ }
    finally { setHistoryLoading(false); }
  }, [selectedCourseId, selectedQuizId]);

  useEffect(() => {
    if (activeTab === 'history') fetchHistory();
  }, [activeTab, fetchHistory]);

  // ---- Audit ----
  const fetchAudit = useCallback(async () => {
    setAuditLoading(true);
    try {
      const res = await canvasSimApi.getAuditLog();
      if (res.success) setAuditLogs(res.logs);
    } catch { /* */ }
    finally { setAuditLoading(false); }
  }, []);

  useEffect(() => {
    if (activeTab === 'audit') fetchAudit();
  }, [activeTab, fetchAudit]);

  // ================================================================
  // RENDER
  // ================================================================

  const activeStudents = students.filter((s) => s.status !== 'deleted');

  return (
    <>
      <style>{panelCss}</style>
      <div className="csim-root">
        {/* BG */}
        <div className="csim-bg-decoration">
          <div className="csim-bg-orb csim-bg-orb-1" />
          <div className="csim-bg-orb csim-bg-orb-2" />
          <div className="csim-bg-orb csim-bg-orb-3" />
        </div>
        <div className="csim-stars">
          {STARS.map((s) => (
            <div
              key={s.id}
              className="csim-star"
              style={{
                top: s.top, left: s.left, width: s.size, height: s.size,
                '--duration': s.duration, '--delay': s.delay,
              } as React.CSSProperties}
            />
          ))}
        </div>

        {/* Glow Lines */}
        <div className="csim-glow-line csim-glow-line-1" />
        <div className="csim-glow-line csim-glow-line-2" />

        {/* Header */}
        <div className="csim-hero-header">
          <div className="csim-hero-icon"><Play size={26} /></div>
          <div className="csim-hero-text">
            <h2>Attempt Simulation</h2>
            <p>Mô phỏng bài làm quiz trên Canvas LMS</p>
          </div>
          <PanelHelpButton panelKey="canvas_sim" />
        </div>

        {/* Sub-tabs */}
        <div className="csim-tabs">
          {([
            { id: 'execute' as SimTab, label: 'Thực thi', icon: Play },
            { id: 'students' as SimTab, label: 'Test Students', icon: Users },
            { id: 'history' as SimTab, label: 'Lịch sử', icon: History },
            { id: 'audit' as SimTab, label: 'Audit Log', icon: Shield },
          ]).map((t) => {
            const Icon = t.icon;
            return (
              <button
                key={t.id}
                className={`csim-tab ${activeTab === t.id ? 'active' : ''}`}
                onClick={() => setActiveTab(t.id)}
              >
                <Icon size={16} /> {t.label}
              </button>
            );
          })}
        </div>

        {/* Content */}
        <div className="csim-content">

          {/* ====================== EXECUTE TAB ====================== */}
          {activeTab === 'execute' && (
            <div className="csim-step-panel">
              {/* Course selector */}
              <div className="csim-card">
                <h3 className="csim-card-title"><BookOpen size={18} /> Chọn khóa học & Quiz</h3>
                <div className="csim-row">
                  <div className="csim-field">
                    <label className="csim-label">Khóa học</label>
                    {coursesLoading ? (
                      <div className="csim-loading"><Loader2 className="spin" size={16} /> Đang tải…</div>
                    ) : (
                      <select
                        className="csim-select"
                        value={selectedCourseId ?? ''}
                        onChange={(e) => {
                          setSelectedCourseId(e.target.value ? Number(e.target.value) : null);
                          setSelectedQuizId(null);
                        }}
                      >
                        <option value="">-- Chọn khóa học --</option>
                        {courses.map((c) => (
                          <option key={c.id} value={c.id}>{c.name} ({c.course_code})</option>
                        ))}
                      </select>
                    )}
                  </div>
                  <div className="csim-field">
                    <label className="csim-label">Quiz</label>
                    {quizzesLoading ? (
                      <div className="csim-loading"><Loader2 className="spin" size={16} /> Đang tải…</div>
                    ) : (
                      <select
                        className="csim-select"
                        value={selectedQuizId ?? ''}
                        onChange={(e) => setSelectedQuizId(e.target.value ? Number(e.target.value) : null)}
                        disabled={!selectedCourseId}
                      >
                        <option value="">-- Chọn quiz --</option>
                        {quizzes.map((q) => (
                          <option key={q.id} value={q.id}>
                            {q.title} {q.published ? '✓' : '(draft)'}
                          </option>
                        ))}
                      </select>
                    )}
                  </div>
                </div>
              </div>

              {/* Pre-Check */}
              {selectedQuizId && (
                <div className="csim-card">
                  <h3 className="csim-card-title">
                    <ClipboardList size={18} /> Pre-Check
                    <button className="csim-btn-icon-sm" onClick={runPreCheck} title="Refresh">
                      <RefreshCw size={14} />
                    </button>
                  </h3>
                  {preCheckLoading ? (
                    <div className="csim-loading"><Loader2 className="spin" size={16} /> Đang kiểm tra…</div>
                  ) : preCheck ? (
                    <div className="csim-precheck">
                      <div className="csim-precheck-row">
                        <span>Quiz published:</span>
                        <span className={preCheck.quiz_published ? 'ok' : 'warn'}>
                          {preCheck.quiz_published ? <CheckCircle size={14} /> : <AlertTriangle size={14} />}
                          {preCheck.quiz_published ? 'Có' : 'Chưa'}
                        </span>
                      </div>
                      <div className="csim-precheck-row">
                        <span>Loại quiz:</span>
                        <span>{{ assignment: 'Bài kiểm tra', practice_quiz: 'Bài luyện tập', graded_survey: 'Khảo sát có điểm', survey: 'Khảo sát' }[preCheck.quiz_type] || preCheck.quiz_type}</span>
                      </div>
                      <div className="csim-precheck-row">
                        <span>Số lần được làm:</span>
                        <span>{preCheck.allowed_attempts === -1 ? 'Không giới hạn' : preCheck.allowed_attempts}</span>
                      </div>
                      {preCheck.access_code_required && (
                        <div className="csim-precheck-row warn">
                          <AlertTriangle size={14} /> Quiz yêu cầu access code
                        </div>
                      )}
                      {preCheck.warnings.map((w, i) => (
                        <div key={i} className="csim-precheck-row warn">
                          <AlertTriangle size={14} /> {w}
                        </div>
                      ))}
                    </div>
                  ) : null}
                </div>
              )}

              {/* Test Student Selector */}
              <div className="csim-card">
                <h3 className="csim-card-title"><Users size={18} /> Chọn Test Student</h3>
                {studentsLoading ? (
                  <div className="csim-loading"><Loader2 className="spin" size={16} /></div>
                ) : activeStudents.length === 0 ? (
                  <p className="csim-muted">Chưa có test student. Tạo ở tab "Test Students".</p>
                ) : (
                  <select
                    className="csim-select"
                    value={selectedStudentId ?? ''}
                    onChange={(e) => setSelectedStudentId(e.target.value || null)}
                  >
                    <option value="">-- Chọn student --</option>
                    {activeStudents.map((s) => (
                      <option key={s.id} value={s.id}>{s.display_name} ({s.email})</option>
                    ))}
                  </select>
                )}
              </div>

              {/* Access Code */}
              {preCheck?.access_code_required && (
                <div className="csim-card">
                  <h3 className="csim-card-title">Access Code</h3>
                  <input
                    className="csim-input"
                    type="text"
                    placeholder="Nhập access code…"
                    value={accessCode}
                    onChange={(e) => setAccessCode(e.target.value)}
                  />
                </div>
              )}

              {/* Answer Builder */}
              {questions.length > 0 && (
                <div className="csim-card">
                  <h3 className="csim-card-title"><ClipboardList size={18} /> Xây dựng đáp án ({questions.length} câu)</h3>
                  {questionsLoading ? (
                    <div className="csim-loading"><Loader2 className="spin" size={16} /></div>
                  ) : (
                    <div className="csim-questions">
                      {questions.map((q, idx) => {
                        const qId = q.id as number;
                        const qText = (q.question_text as string || q.question_name as string || `Câu ${idx + 1}`);
                        const qType = q.question_type as string || 'unknown';
                        const qAnswers = q.answers as Array<Record<string, unknown>> | undefined;

                        return (
                          <div key={qId} className="csim-question-item">
                            <div className="csim-q-header">
                              <span className="csim-q-num">#{idx + 1}</span>
                              <span className="csim-q-type">{qType}</span>
                            </div>
                            <div
                              className="csim-q-text"
                              dangerouslySetInnerHTML={{ __html: qText }}
                            />
                            {/* MCQ: show radio buttons */}
                            {(qType === 'multiple_choice_question' ||
                              qType === 'true_false_question') && qAnswers ? (
                              <div className="csim-q-options">
                                {qAnswers.map((a) => {
                                  const aId = a.id as number;
                                  const aText = a.text as string || a.html as string || '';
                                  return (
                                    <label key={aId} className="csim-q-option">
                                      <input
                                        type="radio"
                                        name={`q-${qId}`}
                                        checked={answers[qId] === aId}
                                        onChange={() => setAnswer(qId, aId)}
                                      />
                                      <span dangerouslySetInnerHTML={{ __html: aText }} />
                                    </label>
                                  );
                                })}
                              </div>
                            ) : (
                              /* Fallback: free text input */
                              <input
                                className="csim-input"
                                type="text"
                                placeholder="Nhập câu trả lời…"
                                value={String(answers[qId] ?? '')}
                                onChange={(e) => setAnswer(qId, e.target.value)}
                              />
                            )}
                          </div>
                        );
                      })}
                    </div>
                  )}
                </div>
              )}

              {/* Execute button */}
              <div className="csim-actions">
                {execError && (
                  <div className="csim-error"><AlertCircle size={16} /> {execError}</div>
                )}
                {execResult && (
                  <div className="csim-success">
                    <CheckCircle size={16} />
                    <span>
                      Thành công! Score: <strong>{String(execResult.score ?? 'N/A')}</strong>
                      {execResult.points_possible != null ? ` / ${execResult.points_possible}` : ''}
                    </span>
                  </div>
                )}
                <button
                  className="csim-btn-primary"
                  disabled={executing || !selectedCourseId || !selectedQuizId || !selectedStudentId}
                  onClick={handleExecute}
                >
                  {executing ? (
                    <><Loader2 className="spin" size={18} /> Đang chạy simulation…</>
                  ) : (
                    <><Play size={18} /> Chạy Simulation</>
                  )}
                </button>
              </div>
            </div>
          )}

          {/* ====================== STUDENTS TAB ====================== */}
          {activeTab === 'students' && (
            <div className="csim-step-panel">
              <div className="csim-card">
                <h3 className="csim-card-title"><Plus size={18} /> Tạo Test Student mới</h3>
                <div className="csim-row">
                  <div className="csim-field">
                    <label className="csim-label">Tên</label>
                    <input
                      className="csim-input"
                      placeholder="Test Student 01"
                      value={newStudentName}
                      onChange={(e) => setNewStudentName(e.target.value)}
                    />
                  </div>
                  <div className="csim-field">
                    <label className="csim-label">Email</label>
                    <input
                      className="csim-input"
                      placeholder="test01@example.com"
                      value={newStudentEmail}
                      onChange={(e) => setNewStudentEmail(e.target.value)}
                    />
                  </div>
                </div>
                <button
                  className="csim-btn-primary"
                  disabled={creatingStudent || !newStudentName || !newStudentEmail}
                  onClick={handleCreateStudent}
                  style={{ marginTop: 12 }}
                >
                  {creatingStudent ? <><Loader2 className="spin" size={16} /> Đang tạo…</> : <><Plus size={16} /> Tạo Student</>}
                </button>
              </div>

              <div className="csim-card">
                <h3 className="csim-card-title">
                  <Users size={18} /> Danh sách ({activeStudents.length})
                  <button className="csim-btn-icon-sm" onClick={fetchStudents} title="Refresh">
                    <RefreshCw size={14} />
                  </button>
                </h3>
                {studentsLoading ? (
                  <div className="csim-loading"><Loader2 className="spin" size={16} /></div>
                ) : studentError ? (
                  <p className="csim-error">{studentError}</p>
                ) : activeStudents.length === 0 ? (
                  <p className="csim-muted">Chưa có test student nào.</p>
                ) : (
                  <div className="csim-table-wrap">
                    <table className="csim-table">
                      <thead>
                        <tr>
                          <th>Tên</th>
                          <th>Email</th>
                          <th>Canvas UID</th>
                          <th>Trạng thái</th>
                          <th>Khóa học</th>
                          <th></th>
                        </tr>
                      </thead>
                      <tbody>
                        {activeStudents.map((s) => (
                          <tr key={s.id}>
                            <td>{s.display_name}</td>
                            <td className="csim-mono">{s.email}</td>
                            <td className="csim-mono">{s.canvas_user_id}</td>
                            <td>
                              <span className={`csim-badge ${s.status}`}>{{ active: 'Hoạt động', enrolled: 'Đã đăng ký', completed: 'Hoàn thành', pending: 'Đang chờ', failed: 'Lỗi', partial: 'Một phần' }[s.status] || s.status}</span>
                            </td>
                            <td>{s.current_course_id ?? '—'}</td>
                            <td>
                              <button className="csim-btn-danger-sm" onClick={() => handleDeleteStudent(s.id)} title="Xóa">
                                <Trash2 size={14} />
                              </button>
                            </td>
                          </tr>
                        ))}
                      </tbody>
                    </table>
                  </div>
                )}
              </div>
            </div>
          )}

          {/* ====================== HISTORY TAB ====================== */}
          {activeTab === 'history' && (
            <div className="csim-step-panel">
              <div className="csim-card">
                <h3 className="csim-card-title">
                  <History size={18} /> Lịch sử Simulation
                  <button className="csim-btn-icon-sm" onClick={fetchHistory} title="Refresh">
                    <RefreshCw size={14} />
                  </button>
                </h3>
                {historyLoading ? (
                  <div className="csim-loading"><Loader2 className="spin" size={16} /></div>
                ) : history.length === 0 ? (
                  <p className="csim-muted">Chưa có lịch sử simulation.</p>
                ) : (
                  <div className="csim-table-wrap">
                    <table className="csim-table">
                      <thead>
                        <tr>
                          <th>Quiz</th>
                          <th>Attempt</th>
                          <th>Score</th>
                          <th>Trạng thái</th>
                          <th>Thời gian</th>
                        </tr>
                      </thead>
                      <tbody>
                        {history.map((r) => (
                          <tr key={r.id}>
                            <td>{{ quiz_id: r.quiz_title || `Quiz #${r.quiz_id}` }['quiz_id']}</td>
                            <td>{r.attempt_number ?? '—'}</td>
                            <td>
                              {r.score != null ? (
                                <>{r.score}{r.points_possible != null ? ` / ${r.points_possible}` : ''}</>
                              ) : '—'}
                            </td>
                            <td>
                              <span className={`csim-badge ${r.status}`}>{{ complete: 'Hoàn thành', pending_review: 'Chờ chấm', untaken: 'Chưa làm', settings_only: 'Chỉ cài đặt' }[r.status] || r.status}</span>
                            </td>
                            <td className="csim-mono csim-small">
                              {new Date(r.started_at).toLocaleString('vi-VN')}
                            </td>
                          </tr>
                        ))}
                      </tbody>
                    </table>
                  </div>
                )}
              </div>
            </div>
          )}

          {/* ====================== AUDIT TAB ====================== */}
          {activeTab === 'audit' && (
            <div className="csim-step-panel">
              <div className="csim-card">
                <h3 className="csim-card-title">
                  <Shield size={18} /> Audit Log
                  <button className="csim-btn-icon-sm" onClick={fetchAudit} title="Refresh">
                    <RefreshCw size={14} />
                  </button>
                </h3>
                {auditLoading ? (
                  <div className="csim-loading"><Loader2 className="spin" size={16} /></div>
                ) : auditLogs.length === 0 ? (
                  <p className="csim-muted">Chưa có audit log.</p>
                ) : (
                  <div className="csim-table-wrap">
                    <table className="csim-table">
                      <thead>
                        <tr>
                          <th>Hành động</th>
                          <th>Canvas UID</th>
                          <th>Quiz</th>
                          <th>Kết quả</th>
                          <th>Thời gian</th>
                        </tr>
                      </thead>
                      <tbody>
                        {auditLogs.map((log) => (
                          <tr key={log.id}>
                            <td>
                              <span className="csim-badge action">{{ enroll_student: 'Đăng ký SV', submit_quiz: 'Nộp bài', create_student: 'Tạo SV', delete_student: 'Xóa SV', unenroll_student: 'Hủy đăng ký' }[log.action] || log.action}</span>
                            </td>
                            <td className="csim-mono">{log.canvas_user_id ?? '—'}</td>
                            <td>{log.canvas_quiz_id ?? '—'}</td>
                            <td>
                              {log.success
                                ? <CheckCircle size={14} className="csim-icon-ok" />
                                : <AlertCircle size={14} className="csim-icon-err" />}
                            </td>
                            <td className="csim-mono csim-small">
                              {new Date(log.created_at).toLocaleString('vi-VN')}
                            </td>
                          </tr>
                        ))}
                      </tbody>
                    </table>
                  </div>
                )}
              </div>
            </div>
          )}
        </div>
      </div>
    </>
  );
};

export default CanvasSimulationPanel;

// ============================================================================
// Embedded CSS
// ============================================================================

const panelCss = `
/* ===== Root ===== */
.csim-root {
  position: relative;
  height: 100%;
  overflow: hidden;
  background: #080b18;
  display: flex;
  flex-direction: column;
}

/* ===== BG ===== */
.csim-root::before {
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
.csim-root::after {
  content: '';
  position: absolute;
  inset: 0;
  background-image:
    linear-gradient(rgba(56, 189, 248, 0.02) 1px, transparent 1px),
    linear-gradient(90deg, rgba(56, 189, 248, 0.02) 1px, transparent 1px);
  background-size: 50px 50px;
  mask-image: radial-gradient(ellipse 80% 70% at 50% 50%, black 20%, transparent 75%);
  -webkit-mask-image: radial-gradient(ellipse 80% 70% at 50% 50%, black 20%, transparent 75%);
  pointer-events: none;
  animation: csim-grid-drift 30s linear infinite;
  z-index: 0;
}
@keyframes csim-grid-drift {
  0% { transform: translate(0, 0); }
  100% { transform: translate(50px, 50px); }
}
.csim-root > * { position: relative; z-index: 1; }

.csim-bg-decoration { position: absolute; inset: 0; pointer-events: none; z-index: 0; overflow: hidden; }
.csim-bg-orb { position: absolute; border-radius: 50%; filter: blur(70px); pointer-events: none; }
.csim-bg-orb-1 {
  width: 350px; height: 350px;
  top: -5%; right: -8%;
  background: radial-gradient(circle, rgba(56, 189, 248, 0.13) 0%, transparent 70%);
  animation: csim-f1 22s ease-in-out infinite;
}
.csim-bg-orb-2 {
  width: 300px; height: 300px;
  bottom: 10%; left: -10%;
  background: radial-gradient(circle, rgba(139, 92, 246, 0.10) 0%, transparent 70%);
  animation: csim-f2 26s ease-in-out infinite;
}
.csim-bg-orb-3 {
  width: 220px; height: 220px;
  top: 40%; right: 15%;
  background: radial-gradient(circle, rgba(34, 211, 238, 0.07) 0%, transparent 70%);
  animation: csim-f3 18s ease-in-out infinite;
}
@keyframes csim-f1 {
  0%, 100% { transform: translate(0, 0) scale(1); }
  33% { transform: translate(-20px, 15px) scale(1.05); }
  66% { transform: translate(10px, -10px) scale(0.97); }
}
@keyframes csim-f2 {
  0%, 100% { transform: translate(0, 0) scale(1); }
  33% { transform: translate(15px, -20px) scale(1.03); }
  66% { transform: translate(-10px, 10px) scale(0.98); }
}
@keyframes csim-f3 {
  0%, 100% { transform: translate(0, 0) scale(1); }
  50% { transform: translate(-15px, 15px) scale(1.08); }
}

/* Stars */
.csim-stars { position: absolute; inset: 0; pointer-events: none; z-index: 0; overflow: hidden; }
.csim-star {
  position: absolute;
  background: #ffffff;
  border-radius: 50%;
  box-shadow: 0 0 6px 1px rgba(255, 255, 255, 0.35);
  opacity: 0;
  animation: csim-twinkle var(--duration, 4s) ease-in-out var(--delay, 0s) infinite;
}
@keyframes csim-twinkle {
  0%, 100% { opacity: 0; transform: scale(0.5); }
  50% { opacity: 0.85; transform: scale(1.3); }
}

/* Glow Lines */
.csim-glow-line {
  position: absolute;
  height: 1px;
  pointer-events: none;
  z-index: 0;
}
.csim-glow-line-1 {
  top: 18%;
  left: 0;
  width: 45%;
  background: linear-gradient(90deg, transparent, rgba(56, 189, 248, 0.30), transparent);
  animation: csim-glow-slide 8s ease-in-out infinite;
}
.csim-glow-line-2 {
  bottom: 25%;
  right: 0;
  width: 38%;
  background: linear-gradient(90deg, transparent, rgba(167, 139, 250, 0.22), transparent);
  animation: csim-glow-slide 10s ease-in-out infinite reverse;
}
@keyframes csim-glow-slide {
  0%, 100% { transform: translateX(-20px); opacity: 0.3; }
  50% { transform: translateX(20px); opacity: 1; }
}

/* ===== Hero Header ===== */
.csim-hero-header {
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
.csim-hero-header::after {
  content: '';
  position: absolute;
  bottom: -1px;
  left: 5%;
  width: 90%;
  height: 1px;
  background: linear-gradient(90deg, transparent, rgba(56, 189, 248, 0.4), rgba(139, 92, 246, 0.3), rgba(34, 211, 238, 0.2), transparent);
}
.csim-hero-icon {
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
.csim-hero-icon::before {
  content: '';
  position: absolute;
  inset: -4px;
  border-radius: 18px;
  border: 1.5px dashed rgba(56, 189, 248, 0.35);
  animation: csim-icon-orbit 12s linear infinite;
}
@keyframes csim-icon-orbit {
  from { transform: rotate(0deg); }
  to { transform: rotate(360deg); }
}
.csim-hero-text h2 {
  font-weight: 700;
  font-size: 1.3rem;
  margin: 0;
  background: linear-gradient(135deg, #e0f2fe 0%, #bae6fd 40%, #7dd3fc 80%, #38bdf8 100%);
  -webkit-background-clip: text;
  -webkit-text-fill-color: transparent;
  background-clip: text;
}
.csim-hero-text p {
  margin: 4px 0 0 0;
  font-size: 0.85rem;
  color: #94a3b8;
}

/* ===== Tabs ===== */
.csim-tabs {
  position: relative;
  z-index: 2;
  display: flex;
  gap: 6px;
  padding: 5px;
  margin: 16px 24px 0;
  background: rgba(22, 33, 55, 0.8);
  backdrop-filter: blur(12px);
  border: 1px solid rgba(56, 189, 248, 0.2);
  border-radius: 14px;
}
.csim-tab {
  flex: 1;
  display: flex;
  align-items: center;
  justify-content: center;
  gap: 8px;
  padding: 12px 20px;
  border: none;
  border-radius: 10px;
  background: transparent;
  color: #64748b;
  font-size: 0.9rem;
  font-weight: 600;
  cursor: pointer;
  transition: all 0.2s ease;
}
.csim-tab:hover {
  color: #cbd5e1;
  background: rgba(56, 189, 248, 0.08);
}
.csim-tab.active {
  background: linear-gradient(135deg, #38bdf8 0%, #0ea5e9 100%);
  color: white;
  box-shadow: 0 2px 12px rgba(56, 189, 248, 0.35);
}

/* ===== Content ===== */
.csim-content {
  flex: 1;
  overflow-y: auto;
  padding: 24px;
  display: flex;
  flex-direction: column;
  gap: 20px;
  background: transparent;
  position: relative;
  z-index: 2;
}
.csim-content::-webkit-scrollbar { width: 8px; }
.csim-content::-webkit-scrollbar-track { background: transparent; }
.csim-content::-webkit-scrollbar-thumb { background: rgba(56, 189, 248, 0.2); border-radius: 10px; }
.csim-content::-webkit-scrollbar-thumb:hover { background: rgba(56, 189, 248, 0.35); }
.csim-step-panel {
  display: flex; flex-direction: column; gap: 16px;
}

/* ===== Cards ===== */
.csim-card {
  background: rgba(22, 33, 55, 0.8);
  backdrop-filter: blur(12px);
  padding: 24px;
  border-radius: 16px;
  border: 1px solid rgba(56, 189, 248, 0.2);
  box-shadow: 0 4px 24px rgba(0, 0, 0, 0.35), inset 0 1px 0 rgba(255, 255, 255, 0.05), 0 0 0 1px rgba(56, 189, 248, 0.06);
  transition: border-color 0.3s ease, box-shadow 0.3s ease;
}
.csim-card:hover {
  border-color: rgba(56, 189, 248, 0.35);
  box-shadow: 0 8px 32px rgba(56, 189, 248, 0.12), inset 0 1px 0 rgba(255, 255, 255, 0.06), 0 0 0 1px rgba(56, 189, 248, 0.1);
}
.csim-card-title {
  display: flex; align-items: center; gap: 8px;
  margin: 0 0 14px;
  font-size: 0.95rem; font-weight: 600;
  color: #e2e8f0;
}

/* ===== Form ===== */
.csim-row { display:flex; gap:16px; flex-wrap:wrap; }
.csim-field { flex:1; min-width:200px; display:flex; flex-direction:column; gap:4px; }
.csim-label { font-size:0.78rem; color:#94a3b8; font-weight:500; }
.csim-select, .csim-input {
  padding: 8px 12px;
  background: rgba(15,23,42,0.8);
  border: 1px solid rgba(255,255,255,0.1);
  border-radius: 8px;
  color: #e2e8f0;
  font-size: 0.85rem;
  outline: none;
  transition: border-color 0.2s;
}
.csim-select:focus, .csim-input:focus { border-color: rgba(16,185,129,0.5); }
.csim-select option { background: #0f172a; color: #e2e8f0; }

/* ===== Buttons ===== */
.csim-btn-primary {
  display: inline-flex; align-items: center; gap: 8px;
  padding: 10px 20px;
  background: linear-gradient(135deg, #10b981, #059669);
  border: none; border-radius: 8px;
  color: #fff; font-size: 0.85rem; font-weight: 600;
  cursor: pointer; transition: all 0.2s;
}
.csim-btn-primary:hover:not(:disabled) { filter: brightness(1.1); transform: translateY(-1px); }
.csim-btn-primary:disabled { opacity: 0.5; cursor: not-allowed; }
.csim-btn-icon-sm {
  background: rgba(255,255,255,0.06);
  border: 1px solid rgba(255,255,255,0.08);
  border-radius: 6px;
  color: #94a3b8;
  padding: 4px 6px;
  cursor: pointer;
  margin-left: auto;
  transition: all 0.2s;
}
.csim-btn-icon-sm:hover { color: #e2e8f0; background: rgba(255,255,255,0.1); }
.csim-btn-danger-sm {
  background: rgba(239,68,68,0.1);
  border: 1px solid rgba(239,68,68,0.2);
  border-radius: 6px;
  color: #f87171;
  padding: 4px 8px;
  cursor: pointer;
  transition: all 0.2s;
}
.csim-btn-danger-sm:hover { background: rgba(239,68,68,0.2); }

/* ===== Utilities ===== */
.csim-loading { display:flex; align-items:center; gap:8px; color:#94a3b8; font-size:0.82rem; padding:8px 0; }
.csim-muted { color:#64748b; font-size:0.82rem; margin:0; }
.csim-error { display:flex; align-items:center; gap:8px; color:#f87171; font-size:0.85rem; padding:8px 12px; background:rgba(239,68,68,0.08); border-radius:8px; margin-bottom:8px; }
.csim-success { display:flex; align-items:center; gap:8px; color:#34d399; font-size:0.85rem; padding:8px 12px; background:rgba(16,185,129,0.08); border-radius:8px; margin-bottom:8px; }
.csim-mono { font-family: 'JetBrains Mono', monospace; font-size: 0.8rem; }
.csim-small { font-size: 0.75rem; }
.csim-icon-ok { color: #34d399; }
.csim-icon-err { color: #f87171; }

/* ===== Actions bar ===== */
.csim-actions { display:flex; flex-direction:column; align-items:flex-start; gap:8px; margin-top:4px; }

/* ===== Pre-Check ===== */
.csim-precheck { display:flex; flex-direction:column; gap:6px; }
.csim-precheck-row { display:flex; align-items:center; gap:8px; font-size:0.83rem; color:#cbd5e1; }
.csim-precheck-row .ok { color:#34d399; display:flex; align-items:center; gap:4px; }
.csim-precheck-row .warn, .csim-precheck-row.warn { color:#fbbf24; display:flex; align-items:center; gap:4px; }

/* ===== Questions ===== */
.csim-questions { display:flex; flex-direction:column; gap:12px; max-height:400px; overflow-y:auto; padding-right:4px; }
.csim-question-item {
  background: rgba(15,23,42,0.5);
  border: 1px solid rgba(255,255,255,0.05);
  border-radius: 8px;
  padding: 12px;
}
.csim-q-header { display:flex; align-items:center; gap:8px; margin-bottom:6px; }
.csim-q-num { font-weight:700; color:#38bdf8; font-size:0.82rem; }
.csim-q-type { font-size:0.72rem; color:#64748b; background:rgba(255,255,255,0.04); padding:2px 6px; border-radius:4px; }
.csim-q-text { font-size:0.83rem; color:#cbd5e1; margin-bottom:8px; line-height:1.4; }
.csim-q-text img { max-width:100%; border-radius:4px; }
.csim-q-options { display:flex; flex-direction:column; gap:4px; }
.csim-q-option { display:flex; align-items:center; gap:8px; font-size:0.82rem; color:#94a3b8; cursor:pointer; padding:4px 0; }
.csim-q-option input[type="radio"] { accent-color: #10b981; }

/* ===== Tables ===== */
.csim-table-wrap { overflow-x:auto; }
.csim-table { width:100%; border-collapse:collapse; font-size:0.82rem; }
.csim-table th {
  text-align:left; padding:8px 12px; color:#94a3b8; font-weight:500;
  border-bottom:1px solid rgba(255,255,255,0.08); font-size:0.78rem; text-transform:uppercase; letter-spacing:0.03em;
}
.csim-table td { padding:8px 12px; color:#cbd5e1; border-bottom:1px solid rgba(255,255,255,0.04); }
.csim-table tbody tr:hover { background:rgba(255,255,255,0.02); }

/* ===== Badges ===== */
.csim-badge {
  display:inline-block; padding:2px 8px; border-radius:4px;
  font-size:0.72rem; font-weight:600; text-transform:uppercase; letter-spacing:0.03em;
}
.csim-badge.active   { background:rgba(16,185,129,0.12); color:#34d399; }
.csim-badge.enrolled  { background:rgba(56,189,248,0.12); color:#38bdf8; }
.csim-badge.completed { background:rgba(16,185,129,0.12); color:#34d399; }
.csim-badge.pending   { background:rgba(251,191,36,0.12); color:#fbbf24; }
.csim-badge.failed    { background:rgba(239,68,68,0.12); color:#f87171; }
.csim-badge.partial   { background:rgba(251,191,36,0.12); color:#fbbf24; }
.csim-badge.action    { background:rgba(139,92,246,0.12); color:#a78bfa; }
`;
