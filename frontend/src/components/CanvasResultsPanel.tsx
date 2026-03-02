import React, { useState, useEffect, useCallback, useRef } from 'react';
import {
  BarChart2,
  BookOpen,
  ClipboardList,
  Download,
  FileSpreadsheet,
  FileText,
  Loader2,
  Users,
  TrendingUp,
  Award,
  ArrowUp,
  ArrowDown,
  Minus,
  ChevronDown,
} from 'lucide-react';
import { canvasResultsApi } from '../api/canvasResults';
import { canvasApi } from '../api/canvas';
import { canvasQuizApi } from '../api/canvasQuiz';
import type { CanvasCourse, CanvasQuiz } from '../types/canvas';
import type {
  QuizResultsAggregation,
  QuizSubmissionSummary,
  CourseGradesAggregation,
} from '../api/canvasResults';

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
const STARS = makeStars(25);

type ResultsTab = 'quiz' | 'course';

// ============================================================================
// Component
// ============================================================================

const CanvasResultsPanel: React.FC = () => {
  const [activeTab, setActiveTab] = useState<ResultsTab>('quiz');

  // Course / Quiz
  const [courses, setCourses] = useState<CanvasCourse[]>([]);
  const [coursesLoading, setCoursesLoading] = useState(false);
  const [selectedCourseId, setSelectedCourseId] = useState<number | null>(null);
  const [quizzes, setQuizzes] = useState<CanvasQuiz[]>([]);
  const [quizzesLoading, setQuizzesLoading] = useState(false);
  const [selectedQuizId, setSelectedQuizId] = useState<number | null>(null);

  // Quiz results
  const [quizResults, setQuizResults] = useState<QuizResultsAggregation | null>(null);
  const [quizResultsLoading, setQuizResultsLoading] = useState(false);

  // Course grades
  const [courseGrades, setCourseGrades] = useState<CourseGradesAggregation | null>(null);
  const [courseGradesLoading, setCourseGradesLoading] = useState(false);

  // Export
  const [exportingQuiz, setExportingQuiz] = useState(false);
  const [exportingCourse, setExportingCourse] = useState(false);
  const [showQuizExportMenu, setShowQuizExportMenu] = useState(false);
  const [showCourseExportMenu, setShowCourseExportMenu] = useState(false);
  const quizExportRef = useRef<HTMLDivElement>(null);
  const courseExportRef = useRef<HTMLDivElement>(null);

  // Close dropdown on outside click
  useEffect(() => {
    const handler = (e: MouseEvent) => {
      if (quizExportRef.current && !quizExportRef.current.contains(e.target as Node)) {
        setShowQuizExportMenu(false);
      }
      if (courseExportRef.current && !courseExportRef.current.contains(e.target as Node)) {
        setShowCourseExportMenu(false);
      }
    };
    document.addEventListener('mousedown', handler);
    return () => document.removeEventListener('mousedown', handler);
  }, []);

  // ---- Data fetch ----
  const fetchCourses = useCallback(async () => {
    setCoursesLoading(true);
    try {
      const res = await canvasApi.fetchCourses();
      if (res.success) setCourses(res.courses);
    } catch { /* */ }
    finally { setCoursesLoading(false); }
  }, []);

  useEffect(() => { fetchCourses(); }, [fetchCourses]);

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

  // ---- Quiz results ----
  const fetchQuizResults = useCallback(async () => {
    if (!selectedCourseId || !selectedQuizId) return;
    setQuizResultsLoading(true);
    try {
      const res = await canvasResultsApi.fetchQuizResults(selectedCourseId, selectedQuizId);
      if (res.success) setQuizResults(res);
    } catch { /* */ }
    finally { setQuizResultsLoading(false); }
  }, [selectedCourseId, selectedQuizId]);

  useEffect(() => {
    if (activeTab === 'quiz' && selectedCourseId && selectedQuizId) fetchQuizResults();
  }, [activeTab, fetchQuizResults, selectedCourseId, selectedQuizId]);

  // ---- Course grades ----
  const fetchCourseGrades = useCallback(async () => {
    if (!selectedCourseId) return;
    setCourseGradesLoading(true);
    try {
      const res = await canvasResultsApi.fetchCourseGrades(selectedCourseId);
      if (res.success) setCourseGrades(res);
    } catch { /* */ }
    finally { setCourseGradesLoading(false); }
  }, [selectedCourseId]);

  useEffect(() => {
    if (activeTab === 'course' && selectedCourseId) fetchCourseGrades();
  }, [activeTab, fetchCourseGrades, selectedCourseId]);

  // ---- Exports ----
  const handleExportQuiz = async (format: 'csv' | 'excel') => {
    if (!selectedCourseId || !selectedQuizId) return;
    setExportingQuiz(true);
    setShowQuizExportMenu(false);
    try {
      if (format === 'excel') {
        await canvasResultsApi.exportQuizExcel(selectedCourseId, selectedQuizId);
      } else {
        await canvasResultsApi.exportQuizCsv(selectedCourseId, selectedQuizId);
      }
    } catch { /* */ }
    finally { setExportingQuiz(false); }
  };

  const handleExportCourse = async (format: 'csv' | 'excel') => {
    if (!selectedCourseId) return;
    setExportingCourse(true);
    setShowCourseExportMenu(false);
    try {
      if (format === 'excel') {
        await canvasResultsApi.exportCourseExcel(selectedCourseId);
      } else {
        await canvasResultsApi.exportCourseCsv(selectedCourseId);
      }
    } catch { /* */ }
    finally { setExportingCourse(false); }
  };

  // ---- Score distribution bars ----
  const renderDistribution = (submissions: QuizSubmissionSummary[], pointsPossible: number) => {
    if (submissions.length === 0 || pointsPossible === 0) return null;
    const bucketCount = 10;
    const buckets = Array(bucketCount).fill(0);
    submissions.forEach((s) => {
      const pct = Math.min(((s.score ?? 0) / pointsPossible) * 100, 100);
      const idx = Math.min(Math.floor(pct / 10), 9);
      buckets[idx]++;
    });
    const maxBucket = Math.max(...buckets, 1);

    return (
      <div className="cres-dist">
        <div className="cres-dist-label-row">
          <span>Phân bố điểm</span>
        </div>
        <div className="cres-dist-bars">
          {buckets.map((count, i) => (
            <div key={i} className="cres-dist-col">
              <div
                className="cres-dist-bar"
                style={{ height: `${(count / maxBucket) * 100}%` }}
                title={`${i * 10}-${i * 10 + 10}%: ${count} submissions`}
              />
              <span className="cres-dist-x">{i * 10}</span>
            </div>
          ))}
        </div>
      </div>
    );
  };

  // ================================================================
  // RENDER
  // ================================================================

  return (
    <>
      <style>{panelCss}</style>
      <div className="cres-root">
        {/* BG */}
        <div className="cres-bg-decoration">
          <div className="cres-bg-orb cres-bg-orb-1" />
          <div className="cres-bg-orb cres-bg-orb-2" />
          <div className="cres-bg-orb cres-bg-orb-3" />
        </div>
        <div className="cres-stars">
          {STARS.map((s) => (
            <div
              key={s.id}
              className="cres-star"
              style={{
                top: s.top, left: s.left, width: s.size, height: s.size,
                '--duration': s.duration, '--delay': s.delay,
              } as React.CSSProperties}
            />
          ))}
        </div>

        {/* Header */}
        <div className="cres-hero-header">
          <div className="cres-hero-icon"><BarChart2 size={26} /></div>
          <div className="cres-hero-text">
            <h2>Results Aggregation</h2>
            <p>Tổng hợp và phân tích kết quả Canvas</p>
          </div>
        </div>

        {/* Sub-tabs */}
        <div className="cres-tabs">
          {([
            { id: 'quiz' as ResultsTab, label: 'Quiz Results', icon: ClipboardList },
            { id: 'course' as ResultsTab, label: 'Course Grades', icon: Award },
          ]).map((t) => {
            const Icon = t.icon;
            return (
              <button
                key={t.id}
                className={`cres-tab ${activeTab === t.id ? 'active' : ''}`}
                onClick={() => setActiveTab(t.id)}
              >
                <Icon size={16} /> {t.label}
              </button>
            );
          })}
        </div>

        {/* Course/Quiz Selector – shared */}
        <div className="cres-content">
          <div className="cres-card">
            <h3 className="cres-card-title"><BookOpen size={18} /> Chọn khóa học {activeTab === 'quiz' && '& Quiz'}</h3>
            <div className="cres-row">
              <div className="cres-field">
                <label className="cres-label">Khóa học</label>
                {coursesLoading ? (
                  <div className="cres-loading"><Loader2 className="spin" size={16} /> Đang tải…</div>
                ) : (
                  <select
                    className="cres-select"
                    value={selectedCourseId ?? ''}
                    onChange={(e) => {
                      setSelectedCourseId(e.target.value ? Number(e.target.value) : null);
                      setSelectedQuizId(null);
                      setQuizResults(null);
                      setCourseGrades(null);
                    }}
                  >
                    <option value="">-- Chọn khóa học --</option>
                    {courses.map((c) => (
                      <option key={c.id} value={c.id}>{c.name} ({c.course_code})</option>
                    ))}
                  </select>
                )}
              </div>
              {activeTab === 'quiz' && (
                <div className="cres-field">
                  <label className="cres-label">Quiz</label>
                  {quizzesLoading ? (
                    <div className="cres-loading"><Loader2 className="spin" size={16} /> Đang tải…</div>
                  ) : (
                    <select
                      className="cres-select"
                      value={selectedQuizId ?? ''}
                      onChange={(e) => {
                        setSelectedQuizId(e.target.value ? Number(e.target.value) : null);
                        setQuizResults(null);
                      }}
                      disabled={!selectedCourseId}
                    >
                      <option value="">-- Chọn quiz --</option>
                      {quizzes.map((q) => (
                        <option key={q.id} value={q.id}>{q.title}</option>
                      ))}
                    </select>
                  )}
                </div>
              )}
            </div>
          </div>

          {/* ====================== QUIZ RESULTS ====================== */}
          {activeTab === 'quiz' && (
            <>
              {quizResultsLoading ? (
                <div className="cres-loading-lg"><Loader2 className="spin" size={24} /> Đang tải kết quả…</div>
              ) : quizResults ? (
                <>
                  {/* Stats cards */}
                  <div className="cres-stats-grid">
                    <div className="cres-stat-card">
                      <div className="cres-stat-icon sub"><Users size={20} /></div>
                      <div className="cres-stat-body">
                        <span className="cres-stat-val">{quizResults.total_submissions}</span>
                        <span className="cres-stat-label">Submissions</span>
                      </div>
                    </div>
                    <div className="cres-stat-card">
                      <div className="cres-stat-icon avg"><TrendingUp size={20} /></div>
                      <div className="cres-stat-body">
                        <span className="cres-stat-val">{quizResults.average_score?.toFixed(1) ?? '—'}</span>
                        <span className="cres-stat-label">Trung bình</span>
                      </div>
                    </div>
                    <div className="cres-stat-card">
                      <div className="cres-stat-icon med"><Minus size={20} /></div>
                      <div className="cres-stat-body">
                        <span className="cres-stat-val">{quizResults.median_score?.toFixed(1) ?? '—'}</span>
                        <span className="cres-stat-label">Trung vị</span>
                      </div>
                    </div>
                    <div className="cres-stat-card">
                      <div className="cres-stat-icon hi"><ArrowUp size={20} /></div>
                      <div className="cres-stat-body">
                        <span className="cres-stat-val">{quizResults.max_score?.toFixed(1) ?? '—'}</span>
                        <span className="cres-stat-label">Cao nhất</span>
                      </div>
                    </div>
                    <div className="cres-stat-card">
                      <div className="cres-stat-icon lo"><ArrowDown size={20} /></div>
                      <div className="cres-stat-body">
                        <span className="cres-stat-val">{quizResults.min_score?.toFixed(1) ?? '—'}</span>
                        <span className="cres-stat-label">Thấp nhất</span>
                      </div>
                    </div>
                    <div className="cres-stat-card">
                      <div className="cres-stat-icon std"><BarChart2 size={20} /></div>
                      <div className="cres-stat-body">
                        <span className="cres-stat-val">{quizResults.std_dev?.toFixed(2) ?? '—'}</span>
                        <span className="cres-stat-label">Std Dev</span>
                      </div>
                    </div>
                  </div>

                  {/* Distribution */}
                  {renderDistribution(quizResults.submissions, quizResults.points_possible ?? 1)}

                  {/* Submissions table */}
                  <div className="cres-card">
                    <h3 className="cres-card-title">
                      <ClipboardList size={18} /> Chi tiết submissions
                      <div className="cres-export-wrap" ref={quizExportRef}>
                        <button
                          className="cres-btn-export"
                          onClick={() => setShowQuizExportMenu((v) => !v)}
                          disabled={exportingQuiz}
                        >
                          {exportingQuiz ? <Loader2 className="spin" size={14} /> : <Download size={14} />}
                          Export
                          <ChevronDown size={12} />
                        </button>
                        {showQuizExportMenu && (
                          <div className="cres-export-menu">
                            <button className="cres-export-item" onClick={() => handleExportQuiz('csv')}>
                              <FileText size={14} /> CSV
                            </button>
                            <button className="cres-export-item" onClick={() => handleExportQuiz('excel')}>
                              <FileSpreadsheet size={14} /> Excel (.xlsx)
                            </button>
                          </div>
                        )}
                      </div>
                    </h3>
                    <div className="cres-table-wrap">
                      <table className="cres-table">
                        <thead>
                          <tr>
                            <th>User</th>
                            <th>Attempt</th>
                            <th>Score</th>
                            <th>%</th>
                            <th>Trạng thái</th>
                            <th>Nộp lúc</th>
                          </tr>
                        </thead>
                        <tbody>
                          {quizResults.submissions.map((s, i) => {
                            const pct = (quizResults.points_possible ?? 1) > 0
                              ? ((s.score ?? 0) / (quizResults.points_possible ?? 1)) * 100
                              : 0;
                            return (
                              <tr key={i}>
                                <td>{s.user_name ?? `User #${s.user_id}`}</td>
                                <td>{s.attempt}</td>
                                <td className="cres-mono">
                                  {s.score != null ? s.score.toFixed(1) : '—'}
                                  {quizResults.points_possible != null && ` / ${quizResults.points_possible}`}
                                </td>
                                <td>
                                  <span className={`cres-pct ${pct >= 80 ? 'hi' : pct >= 50 ? 'mid' : 'lo'}`}>
                                    {pct.toFixed(0)}%
                                  </span>
                                </td>
                                <td>
                                  <span className={`cres-badge ${s.workflow_state}`}>
                                    {s.workflow_state}
                                  </span>
                                </td>
                                <td className="cres-mono cres-small">
                                  {s.finished_at ? new Date(s.finished_at).toLocaleString('vi-VN') : '—'}
                                </td>
                              </tr>
                            );
                          })}
                        </tbody>
                      </table>
                    </div>
                  </div>
                </>
              ) : selectedCourseId && selectedQuizId ? (
                <div className="cres-empty">Chọn quiz và bấm tải dữ liệu.</div>
              ) : (
                <div className="cres-empty">Chọn khóa học và quiz ở trên để xem kết quả.</div>
              )}
            </>
          )}

          {/* ====================== COURSE GRADES ====================== */}
          {activeTab === 'course' && (
            <>
              {courseGradesLoading ? (
                <div className="cres-loading-lg"><Loader2 className="spin" size={24} /> Đang tải điểm…</div>
              ) : courseGrades ? (
                <>
                  {/* Stats */}
                  <div className="cres-stats-grid">
                    <div className="cres-stat-card">
                      <div className="cres-stat-icon sub"><Users size={20} /></div>
                      <div className="cres-stat-body">
                        <span className="cres-stat-val">{courseGrades.total_students}</span>
                        <span className="cres-stat-label">Sinh viên</span>
                      </div>
                    </div>
                    <div className="cres-stat-card">
                      <div className="cres-stat-icon avg"><TrendingUp size={20} /></div>
                      <div className="cres-stat-body">
                        <span className="cres-stat-val">{courseGrades.average_current_score?.toFixed(1) ?? '—'}%</span>
                        <span className="cres-stat-label">TB toàn khóa</span>
                      </div>
                    </div>
                  </div>

                  {/* Table */}
                  <div className="cres-card">
                    <h3 className="cres-card-title">
                      <Award size={18} /> Bảng điểm
                      <div className="cres-export-wrap" ref={courseExportRef}>
                        <button
                          className="cres-btn-export"
                          onClick={() => setShowCourseExportMenu((v) => !v)}
                          disabled={exportingCourse}
                        >
                          {exportingCourse ? <Loader2 className="spin" size={14} /> : <Download size={14} />}
                          Export
                          <ChevronDown size={12} />
                        </button>
                        {showCourseExportMenu && (
                          <div className="cres-export-menu">
                            <button className="cres-export-item" onClick={() => handleExportCourse('csv')}>
                              <FileText size={14} /> CSV
                            </button>
                            <button className="cres-export-item" onClick={() => handleExportCourse('excel')}>
                              <FileSpreadsheet size={14} /> Excel (.xlsx)
                            </button>
                          </div>
                        )}
                      </div>
                    </h3>
                    <div className="cres-table-wrap">
                      <table className="cres-table">
                        <thead>
                          <tr>
                            <th>Sinh viên</th>
                            <th>Trạng thái</th>
                            <th>Current Score</th>
                            <th>Final Score</th>
                            <th>Grade</th>
                          </tr>
                        </thead>
                        <tbody>
                          {courseGrades.enrollments.map((e, i) => (
                            <tr key={i}>
                              <td>{e.user_name}</td>
                              <td className="cres-mono">{e.enrollment_state ?? '—'}</td>
                              <td>
                                {e.current_score != null ? (
                                  <span className={`cres-pct ${e.current_score >= 80 ? 'hi' : e.current_score >= 50 ? 'mid' : 'lo'}`}>
                                    {e.current_score.toFixed(1)}%
                                  </span>
                                ) : '—'}
                              </td>
                              <td>
                                {e.final_score != null ? `${e.final_score.toFixed(1)}%` : '—'}
                              </td>
                              <td>
                                <span className="cres-grade">{e.current_grade ?? e.final_grade ?? '—'}</span>
                              </td>
                            </tr>
                          ))}
                        </tbody>
                      </table>
                    </div>
                  </div>
                </>
              ) : selectedCourseId ? (
                <div className="cres-empty">Đang chờ dữ liệu…</div>
              ) : (
                <div className="cres-empty">Chọn khóa học ở trên để xem bảng điểm.</div>
              )}
            </>
          )}
        </div>
      </div>
    </>
  );
};

export default CanvasResultsPanel;

// ============================================================================
// Embedded CSS
// ============================================================================

const panelCss = `
/* ===== Root ===== */
.cres-root {
  position: relative; height: 100%;
  overflow-y: auto; overflow-x: hidden;
  background: #080b18;
  display: flex; flex-direction: column;
  padding: 0 0 32px 0;
}
.cres-root::before {
  content:''; position:fixed; inset:0;
  background:
    radial-gradient(ellipse 80% 60% at 20% 10%, rgba(139,92,246,0.10) 0%, transparent 60%),
    radial-gradient(ellipse 60% 50% at 80% 90%, rgba(56,189,248,0.08) 0%, transparent 60%),
    radial-gradient(ellipse 50% 40% at 50% 50%, rgba(244,114,182,0.05) 0%, transparent 60%);
  pointer-events:none; z-index:0;
}

/* ===== BG ===== */
.cres-bg-decoration { pointer-events:none; z-index:0; }
.cres-bg-orb { position:absolute; border-radius:50%; filter:blur(80px); opacity:0.35; z-index:0; }
.cres-bg-orb-1 { width:400px;height:400px;background:radial-gradient(circle,rgba(139,92,246,0.18)0%,transparent 70%);top:-120px;left:-100px;animation:cres-f1 20s ease-in-out infinite; }
.cres-bg-orb-2 { width:350px;height:350px;background:radial-gradient(circle,rgba(56,189,248,0.14)0%,transparent 70%);bottom:-80px;right:-60px;animation:cres-f2 24s ease-in-out infinite; }
.cres-bg-orb-3 { width:250px;height:250px;background:radial-gradient(circle,rgba(244,114,182,0.10)0%,transparent 70%);top:50%;left:50%;transform:translate(-50%,-50%);animation:cres-f3 18s ease-in-out infinite; }
@keyframes cres-f1{0%,100%{transform:translate(0,0)}50%{transform:translate(30px,20px)}}
@keyframes cres-f2{0%,100%{transform:translate(0,0)}50%{transform:translate(-25px,-15px)}}
@keyframes cres-f3{0%,100%{transform:translate(-50%,-50%)}50%{transform:translate(-45%,-55%)}}
.cres-stars{position:absolute;inset:0;z-index:0;pointer-events:none;}
.cres-star{position:absolute;background:#fff;border-radius:50%;animation:cres-twinkle var(--duration) var(--delay) ease-in-out infinite;}
@keyframes cres-twinkle{0%,100%{opacity:0.2}50%{opacity:0.9}}

/* ===== Header ===== */
.cres-hero-header {
  position:relative; z-index:1;
  display:flex; align-items:center; gap:16px;
  padding:28px 32px 12px;
}
.cres-hero-icon {
  width:52px; height:52px;
  background:linear-gradient(135deg, rgba(139,92,246,0.25), rgba(56,189,248,0.18));
  border:1px solid rgba(139,92,246,0.3);
  border-radius:14px;
  display:flex; align-items:center; justify-content:center;
  color:#a78bfa;
}
.cres-hero-text h2 { margin:0; font-size:1.35rem; color:#f1f5f9; font-weight:700; }
.cres-hero-text p  { margin:2px 0 0; font-size:0.85rem; color:#94a3b8; }

/* ===== Tabs ===== */
.cres-tabs {
  position:relative; z-index:1;
  display:flex; gap:4px;
  padding:8px 32px;
  border-bottom:1px solid rgba(255,255,255,0.06);
}
.cres-tab {
  display:flex; align-items:center; gap:6px;
  padding:8px 16px;
  background:transparent; border:1px solid transparent; border-radius:8px;
  color:#94a3b8; font-size:0.82rem; cursor:pointer; transition:all 0.2s;
}
.cres-tab:hover { color:#e2e8f0; background:rgba(255,255,255,0.04); }
.cres-tab.active { color:#a78bfa; background:rgba(139,92,246,0.08); border-color:rgba(139,92,246,0.25); }

/* ===== Content ===== */
.cres-content { position:relative; z-index:1; flex:1; padding:16px 32px; display:flex; flex-direction:column; gap:16px; }

/* ===== Cards ===== */
.cres-card {
  background:rgba(15,23,42,0.65);
  border:1px solid rgba(255,255,255,0.06);
  border-radius:12px; padding:20px;
  backdrop-filter:blur(12px);
}
.cres-card-title {
  display:flex; align-items:center; gap:8px;
  margin:0 0 14px; font-size:0.95rem; font-weight:600; color:#e2e8f0;
}

/* ===== Form ===== */
.cres-row { display:flex; gap:16px; flex-wrap:wrap; }
.cres-field { flex:1; min-width:200px; display:flex; flex-direction:column; gap:4px; }
.cres-label { font-size:0.78rem; color:#94a3b8; font-weight:500; }
.cres-select {
  padding:8px 12px; background:rgba(15,23,42,0.8);
  border:1px solid rgba(255,255,255,0.1); border-radius:8px;
  color:#e2e8f0; font-size:0.85rem; outline:none; transition:border-color 0.2s;
}
.cres-select:focus { border-color:rgba(139,92,246,0.5); }
.cres-select option { background:#0f172a; color:#e2e8f0; }

/* ===== Stats Grid ===== */
.cres-stats-grid {
  display:grid;
  grid-template-columns:repeat(auto-fill, minmax(170px, 1fr));
  gap:12px;
}
.cres-stat-card {
  display:flex; align-items:center; gap:12px;
  background:rgba(15,23,42,0.65);
  border:1px solid rgba(255,255,255,0.06);
  border-radius:12px; padding:16px;
  backdrop-filter:blur(12px);
}
.cres-stat-icon {
  width:40px; height:40px; border-radius:10px;
  display:flex; align-items:center; justify-content:center;
}
.cres-stat-icon.sub { background:rgba(56,189,248,0.12); color:#38bdf8; }
.cres-stat-icon.avg { background:rgba(16,185,129,0.12); color:#34d399; }
.cres-stat-icon.med { background:rgba(251,191,36,0.12); color:#fbbf24; }
.cres-stat-icon.hi  { background:rgba(16,185,129,0.12); color:#34d399; }
.cres-stat-icon.lo  { background:rgba(239,68,68,0.12); color:#f87171; }
.cres-stat-icon.std { background:rgba(139,92,246,0.12); color:#a78bfa; }
.cres-stat-body { display:flex; flex-direction:column; }
.cres-stat-val { font-size:1.3rem; font-weight:700; color:#f1f5f9; line-height:1.1; }
.cres-stat-label { font-size:0.72rem; color:#94a3b8; margin-top:2px; }

/* ===== Distribution ===== */
.cres-dist {
  background:rgba(15,23,42,0.65);
  border:1px solid rgba(255,255,255,0.06);
  border-radius:12px; padding:20px; backdrop-filter:blur(12px);
}
.cres-dist-label-row { font-size:0.85rem; font-weight:600; color:#e2e8f0; margin-bottom:12px; }
.cres-dist-bars {
  display:flex; align-items:flex-end; gap:6px; height:120px;
}
.cres-dist-col { flex:1; display:flex; flex-direction:column; align-items:center; height:100%; justify-content:flex-end; }
.cres-dist-bar {
  width:100%; min-width:12px;
  background:linear-gradient(180deg, #a78bfa 0%, #6d28d9 100%);
  border-radius:4px 4px 0 0;
  transition:height 0.3s;
}
.cres-dist-x { font-size:0.65rem; color:#64748b; margin-top:4px; }

/* ===== Tables ===== */
.cres-table-wrap { overflow-x:auto; }
.cres-table { width:100%; border-collapse:collapse; font-size:0.82rem; }
.cres-table th {
  text-align:left; padding:8px 12px; color:#94a3b8; font-weight:500;
  border-bottom:1px solid rgba(255,255,255,0.08); font-size:0.78rem;
  text-transform:uppercase; letter-spacing:0.03em;
}
.cres-table td { padding:8px 12px; color:#cbd5e1; border-bottom:1px solid rgba(255,255,255,0.04); }
.cres-table tbody tr:hover { background:rgba(255,255,255,0.02); }
.cres-mono { font-family:'JetBrains Mono',monospace; font-size:0.8rem; }
.cres-small { font-size:0.75rem; }

/* ===== Badges ===== */
.cres-badge {
  display:inline-block; padding:2px 8px; border-radius:4px;
  font-size:0.72rem; font-weight:600; text-transform:uppercase; letter-spacing:0.03em;
}
.cres-badge.complete   { background:rgba(16,185,129,0.12); color:#34d399; }
.cres-badge.pending_review { background:rgba(251,191,36,0.12); color:#fbbf24; }
.cres-badge.untaken    { background:rgba(100,116,139,0.12); color:#94a3b8; }

/* ===== Percent ===== */
.cres-pct { font-weight:600; font-size:0.82rem; }
.cres-pct.hi  { color:#34d399; }
.cres-pct.mid { color:#fbbf24; }
.cres-pct.lo  { color:#f87171; }
.cres-grade { font-weight:700; color:#e2e8f0; }

/* ===== Buttons ===== */
.cres-export-wrap {
  position: relative;
  margin-left: auto;
}
.cres-btn-export {
  display:inline-flex; align-items:center; gap:6px;
  padding:6px 14px;
  background:rgba(139,92,246,0.10);
  border:1px solid rgba(139,92,246,0.25);
  border-radius:6px;
  color:#a78bfa; font-size:0.78rem; font-weight:500;
  cursor:pointer; transition:all 0.2s;
}
.cres-btn-export:hover:not(:disabled) { background:rgba(139,92,246,0.18); }
.cres-btn-export:disabled { opacity:0.5; cursor:not-allowed; }
.cres-export-menu {
  position: absolute;
  top: calc(100% + 4px);
  right: 0;
  z-index: 50;
  min-width: 150px;
  background: #151a2e;
  border: 1px solid rgba(139,92,246,0.25);
  border-radius: 8px;
  box-shadow: 0 8px 24px rgba(0,0,0,0.45);
  padding: 4px;
  animation: cres-fade-in 0.15s ease;
}
@keyframes cres-fade-in {
  from { opacity:0; transform:translateY(-4px); }
  to   { opacity:1; transform:translateY(0); }
}
.cres-export-item {
  display: flex; align-items: center; gap: 8px;
  width: 100%;
  padding: 8px 12px;
  background: transparent;
  border: none;
  color: #cbd5e1;
  font-size: 0.8rem;
  cursor: pointer;
  border-radius: 6px;
  transition: background 0.15s;
}
.cres-export-item:hover {
  background: rgba(139,92,246,0.15);
  color: #e0d4fd;
}

/* ===== Misc ===== */
.cres-loading { display:flex; align-items:center; gap:8px; color:#94a3b8; font-size:0.82rem; padding:8px 0; }
.cres-loading-lg { display:flex; align-items:center; justify-content:center; gap:10px; color:#94a3b8; font-size:0.9rem; padding:40px 0; }
.cres-empty { color:#64748b; font-size:0.85rem; text-align:center; padding:32px 16px; }

/* ===== Spinner ===== */
.spin { animation: cres-spin 1s linear infinite; }
@keyframes cres-spin { from{transform:rotate(0deg)}to{transform:rotate(360deg)} }
`;
