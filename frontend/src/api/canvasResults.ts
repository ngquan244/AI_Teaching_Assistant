// ============================================================================
// Canvas Results Aggregation API Service
// ============================================================================

import { apiClient } from './client';
import { getCanvasHeaders } from './canvas';

// ---- Types ----

export interface QuizSubmissionSummary {
  user_id: number;
  user_name?: string | null;
  submission_id: number;
  attempt: number;
  score?: number | null;
  kept_score?: number | null;
  points_possible?: number | null;
  started_at?: string | null;
  finished_at?: string | null;
  workflow_state: string;
}

export interface QuizResultsAggregation {
  success: boolean;
  quiz_id: number;
  quiz_title: string;
  points_possible?: number | null;
  total_submissions: number;
  graded_count: number;
  average_score?: number | null;
  median_score?: number | null;
  max_score?: number | null;
  min_score?: number | null;
  std_dev?: number | null;
  score_distribution: Record<string, number>;
  submissions: QuizSubmissionSummary[];
  error?: string;
}

export interface EnrollmentGradeItem {
  user_id: number;
  user_name?: string | null;
  enrollment_id: number;
  enrollment_state: string;
  current_score?: number | null;
  final_score?: number | null;
  current_grade?: string | null;
  final_grade?: string | null;
}

export interface CourseGradesAggregation {
  success: boolean;
  course_id: number;
  course_name?: string | null;
  total_students: number;
  average_current_score?: number | null;
  average_final_score?: number | null;
  max_current_score?: number | null;
  min_current_score?: number | null;
  grade_distribution: Record<string, number>;
  enrollments: EnrollmentGradeItem[];
  error?: string;
}

// ---- API Functions ----

export async function fetchQuizResults(
  courseId: number,
  quizId: number,
): Promise<QuizResultsAggregation> {
  try {
    const headers = await getCanvasHeaders();
    const resp = await apiClient.get(`/api/canvas-results/quiz/${courseId}/${quizId}`, { headers });
    return resp.data;
  } catch (error: unknown) {
    const err = error as { response?: { data?: { detail?: string } }; message?: string };
    return {
      success: false,
      quiz_id: quizId,
      quiz_title: '',
      total_submissions: 0,
      graded_count: 0,
      score_distribution: {},
      submissions: [],
      error: err.response?.data?.detail || err.message || 'Failed to fetch quiz results',
    };
  }
}

export async function fetchCourseGrades(courseId: number): Promise<CourseGradesAggregation> {
  try {
    const headers = await getCanvasHeaders();
    const resp = await apiClient.get(`/api/canvas-results/course/${courseId}/grades`, { headers });
    return resp.data;
  } catch (error: unknown) {
    const err = error as { response?: { data?: { detail?: string } }; message?: string };
    return {
      success: false,
      course_id: courseId,
      total_students: 0,
      grade_distribution: {},
      enrollments: [],
      error: err.response?.data?.detail || err.message || 'Failed to fetch course grades',
    };
  }
}

export async function exportQuizCsv(courseId: number, quizId: number): Promise<void> {
  try {
    const headers = await getCanvasHeaders();
    const resp = await apiClient.get(`/api/canvas-results/export/quiz/${courseId}/${quizId}`, {
      headers,
      responseType: 'blob',
    });
    const url = window.URL.createObjectURL(new Blob([resp.data]));
    const a = document.createElement('a');
    a.href = url;
    a.download = `quiz_${quizId}_results.csv`;
    document.body.appendChild(a);
    a.click();
    a.remove();
    window.URL.revokeObjectURL(url);
  } catch {
    throw new Error('Failed to export quiz results');
  }
}

export async function exportQuizExcel(courseId: number, quizId: number): Promise<void> {
  try {
    const headers = await getCanvasHeaders();
    const resp = await apiClient.get(`/api/canvas-results/export/quiz/${courseId}/${quizId}/excel`, {
      headers,
      responseType: 'blob',
    });
    const url = window.URL.createObjectURL(new Blob([resp.data]));
    const a = document.createElement('a');
    a.href = url;
    a.download = `quiz_${quizId}_results.xlsx`;
    document.body.appendChild(a);
    a.click();
    a.remove();
    window.URL.revokeObjectURL(url);
  } catch {
    throw new Error('Failed to export quiz results as Excel');
  }
}

export async function exportCourseCsv(courseId: number): Promise<void> {
  try {
    const headers = await getCanvasHeaders();
    const resp = await apiClient.get(`/api/canvas-results/export/course/${courseId}`, {
      headers,
      responseType: 'blob',
    });
    const url = window.URL.createObjectURL(new Blob([resp.data]));
    const a = document.createElement('a');
    a.href = url;
    a.download = `course_${courseId}_grades.csv`;
    document.body.appendChild(a);
    a.click();
    a.remove();
    window.URL.revokeObjectURL(url);
  } catch {
    throw new Error('Failed to export course grades');
  }
}

export async function exportCourseExcel(courseId: number): Promise<void> {
  try {
    const headers = await getCanvasHeaders();
    const resp = await apiClient.get(`/api/canvas-results/export/course/${courseId}/excel`, {
      headers,
      responseType: 'blob',
    });
    const url = window.URL.createObjectURL(new Blob([resp.data]));
    const a = document.createElement('a');
    a.href = url;
    a.download = `course_${courseId}_grades.xlsx`;
    document.body.appendChild(a);
    a.click();
    a.remove();
    window.URL.revokeObjectURL(url);
  } catch {
    throw new Error('Failed to export course grades as Excel');
  }
}

export const canvasResultsApi = {
  fetchQuizResults,
  fetchCourseGrades,
  exportQuizCsv,
  exportQuizExcel,
  exportCourseCsv,
  exportCourseExcel,
};

export default canvasResultsApi;
