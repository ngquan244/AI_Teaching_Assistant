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
import PanelHelpButton from './PanelHelpButton';
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

        <div className="cres-glow-line cres-glow-line-1" />
        <div className="cres-glow-line cres-glow-line-2" />

        {/* Header */}
        <div className="cres-hero-header">
          <div className="cres-hero-icon"><BarChart2 size={26} /></div>
          <div className="cres-hero-text">
            <h2>Results Aggregation</h2>
            <p>Tổng hợp và phân tích kết quả Canvas</p>
          </div>
          <PanelHelpButton panelKey="canvas_results" />
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
                        <span className="cres-stat-label">Độ lệch chuẩn</span>
                      </div>
                    </div>
                  </div>

                  {/* Distribution */}
                  {renderDistribution(quizResults.submissions, quizResults.points_possible ?? 1)}

                  {/* Submissions table */}
                  <div className="cres-card">
                    <h3 className="cres-card-title">
                      <ClipboardList size={18} /> Chi tiết bài nộp
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
                            <th>Sinh viên</th>
                            <th>Lần làm</th>
                            <th>Điểm</th>
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
                                <td>{s.user_name ?? `Sinh viên #${s.user_id}`}</td>
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
                                    {{ complete: 'Hoàn thành', pending_review: 'Chờ chấm', untaken: 'Chưa làm', settings_only: 'Chỉ cài đặt', preview: 'Xem trước' }[s.workflow_state] || s.workflow_state}
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
                            <th>Điểm hiện tại</th>
                            <th>Điểm cuối</th>
                            <th>Xếp loại</th>
                          </tr>
                        </thead>
                        <tbody>
                          {courseGrades.enrollments.map((e, i) => (
                            <tr key={i}>
                              <td>{e.user_name}</td>
                              <td className="cres-mono">{{ active: 'Đang học', completed: 'Hoàn thành', invited: 'Đã mời', inactive: 'Không hoạt động' }[e.enrollment_state ?? ''] ?? e.enrollment_state ?? '—'}</td>
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
  position: relative;
  height: 100%;
  overflow: hidden;
  background: #080b18;
  display: flex;
  flex-direction: column;
}
.cres-root::before {
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
.cres-root::after {
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
  animation: cres-grid-drift 30s linear infinite;
  z-index: 0;
}
@keyframes cres-grid-drift {
  0% { transform: translate(0, 0); }
  100% { transform: translate(50px, 50px); }
}
.cres-root > * { position: relative; z-index: 1; }

/* ===== BG ===== */
.cres-bg-decoration { position: absolute; inset: 0; pointer-events: none; z-index: 0; overflow: hidden; }
.cres-bg-orb { position: absolute; border-radius: 50%; filter: blur(70px); pointer-events: none; }
.cres-bg-orb-1 {
  width: 350px; height: 350px;
  top: -5%; right: -8%;
  background: radial-gradient(circle, rgba(56, 189, 248, 0.13) 0%, transparent 70%);
  animation: cres-f1 22s ease-in-out infinite;
}
.cres-bg-orb-2 {
  width: 300px; height: 300px;
  bottom: 10%; left: -10%;
  background: radial-gradient(circle, rgba(139, 92, 246, 0.10) 0%, transparent 70%);
  animation: cres-f2 26s ease-in-out infinite;
}
.cres-bg-orb-3 {
  width: 220px; height: 220px;
  top: 40%; right: 15%;
  background: radial-gradient(circle, rgba(34, 211, 238, 0.07) 0%, transparent 70%);
  animation: cres-f3 18s ease-in-out infinite;
}
@keyframes cres-f1 {
  0%, 100% { transform: translate(0, 0) scale(1); }
  33% { transform: translate(-20px, 15px) scale(1.05); }
  66% { transform: translate(10px, -10px) scale(0.97); }
}
@keyframes cres-f2 {
  0%, 100% { transform: translate(0, 0) scale(1); }
  33% { transform: translate(15px, -20px) scale(1.03); }
  66% { transform: translate(-10px, 10px) scale(0.98); }
}
@keyframes cres-f3 {
  0%, 100% { transform: translate(0, 0) scale(1); }
  50% { transform: translate(-15px, 15px) scale(1.08); }
}

/* Stars */
.cres-stars { position: absolute; inset: 0; pointer-events: none; z-index: 0; overflow: hidden; }
.cres-star {
  position: absolute;
  background: #ffffff;
  border-radius: 50%;
  box-shadow: 0 0 6px 1px rgba(255, 255, 255, 0.35);
  opacity: 0;
  animation: cres-twinkle var(--duration, 4s) ease-in-out var(--delay, 0s) infinite;
}
@keyframes cres-twinkle {
  0%, 100% { opacity: 0; transform: scale(0.5); }
  50% { opacity: 0.85; transform: scale(1.3); }
}

/* Glow Lines */
.cres-glow-line {
  position: absolute;
  height: 1px;
  pointer-events: none;
  z-index: 0;
}
.cres-glow-line-1 {
  top: 18%;
  left: 0;
  width: 45%;
  background: linear-gradient(90deg, transparent, rgba(56, 189, 248, 0.30), transparent);
  animation: cres-glow-slide 8s ease-in-out infinite;
}
.cres-glow-line-2 {
  bottom: 25%;
  right: 0;
  width: 38%;
  background: linear-gradient(90deg, transparent, rgba(167, 139, 250, 0.22), transparent);
  animation: cres-glow-slide 10s ease-in-out infinite reverse;
}
@keyframes cres-glow-slide {
  0%, 100% { transform: translateX(-20px); opacity: 0.3; }
  50% { transform: translateX(20px); opacity: 1; }
}

/* ===== Hero Header ===== */
.cres-hero-header {
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
.cres-hero-header::after {
  content: '';
  position: absolute;
  bottom: -1px;
  left: 5%;
  width: 90%;
  height: 1px;
  background: linear-gradient(90deg, transparent, rgba(56, 189, 248, 0.4), rgba(139, 92, 246, 0.3), rgba(34, 211, 238, 0.2), transparent);
}
.cres-hero-icon {
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
.cres-hero-icon::before {
  content: '';
  position: absolute;
  inset: -4px;
  border-radius: 18px;
  border: 1.5px dashed rgba(56, 189, 248, 0.35);
  animation: cres-icon-orbit 12s linear infinite;
}
@keyframes cres-icon-orbit {
  from { transform: rotate(0deg); }
  to { transform: rotate(360deg); }
}
.cres-hero-text h2 {
  font-weight: 700;
  font-size: 1.3rem;
  margin: 0;
  background: linear-gradient(135deg, #e0f2fe 0%, #bae6fd 40%, #7dd3fc 80%, #38bdf8 100%);
  -webkit-background-clip: text;
  -webkit-text-fill-color: transparent;
  background-clip: text;
}
.cres-hero-text p {
  margin: 4px 0 0 0;
  font-size: 0.85rem;
  color: #94a3b8;
}

/* ===== Tabs ===== */
.cres-tabs {
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
.cres-tab {
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
.cres-tab:hover {
  color: #cbd5e1;
  background: rgba(56, 189, 248, 0.08);
}
.cres-tab.active {
  background: linear-gradient(135deg, #38bdf8 0%, #0ea5e9 100%);
  color: white;
  box-shadow: 0 2px 12px rgba(56, 189, 248, 0.35);
}

/* ===== Content ===== */
.cres-content {
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
.cres-content::-webkit-scrollbar { width: 8px; }
.cres-content::-webkit-scrollbar-track { background: transparent; }
.cres-content::-webkit-scrollbar-thumb { background: rgba(56, 189, 248, 0.2); border-radius: 10px; }
.cres-content::-webkit-scrollbar-thumb:hover { background: rgba(56, 189, 248, 0.35); }

/* ===== Cards ===== */
.cres-card {
  background: rgba(22, 33, 55, 0.8);
  backdrop-filter: blur(12px);
  padding: 24px;
  border-radius: 16px;
  border: 1px solid rgba(56, 189, 248, 0.2);
  box-shadow: 0 4px 24px rgba(0, 0, 0, 0.35), inset 0 1px 0 rgba(255, 255, 255, 0.05), 0 0 0 1px rgba(56, 189, 248, 0.06);
  transition: border-color 0.3s ease, box-shadow 0.3s ease;
}
.cres-card:hover {
  border-color: rgba(56, 189, 248, 0.35);
  box-shadow: 0 8px 32px rgba(56, 189, 248, 0.12), inset 0 1px 0 rgba(255, 255, 255, 0.06), 0 0 0 1px rgba(56, 189, 248, 0.1);
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
