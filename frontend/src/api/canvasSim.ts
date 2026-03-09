// ============================================================================
// Canvas Simulation API Service
// ============================================================================

import { apiClient } from './client';
import { getCanvasHeaders } from './canvas';

// ---- Types ----

export interface TestStudent {
  id: string;
  canvas_user_id: number;
  display_name: string;
  email: string;
  status: string;
  canvas_domain: string;
  current_course_id?: number | null;
  current_enrollment_id?: number | null;
  created_at: string;
}

export interface SimulationAnswerItem {
  question_id: number;
  answer: unknown;
}

export interface SimulationExecuteRequest {
  course_id: number;
  quiz_id: number;
  test_student_id: string;
  answers: SimulationAnswerItem[];
  access_code?: string;
}

export interface SimulationBatchRequest {
  course_id: number;
  quiz_id: number;
  test_student_id: string;
  answer_sets: SimulationAnswerItem[][];
  access_code?: string;
}

export interface SimulationRunResult {
  id: string;
  course_id: number;
  quiz_id: number;
  quiz_title?: string;
  test_student_name?: string;
  canvas_submission_id?: number;
  attempt_number?: number;
  score?: number | null;
  kept_score?: number | null;
  points_possible?: number | null;
  status: string;
  error_message?: string | null;
  started_at: string;
  completed_at?: string | null;
}

export interface PreCheckResponse {
  success: boolean;
  course_published?: boolean;
  quiz_published?: boolean;
  quiz_type?: string;
  allowed_attempts?: number;
  ip_filter?: string | null;
  access_code_required: boolean;
  warnings: string[];
  error?: string;
}

export interface AuditLogEntry {
  id: string;
  action: string;
  canvas_domain: string;
  canvas_course_id?: number | null;
  canvas_user_id?: number | null;
  canvas_quiz_id?: number | null;
  canvas_submission_id?: number | null;
  success: boolean;
  detail?: string | null;
  created_at: string;
}

// ---- API Functions ----

export async function preCheckQuiz(courseId: number, quizId: number): Promise<PreCheckResponse> {
  try {
    const headers = await getCanvasHeaders();
    const resp = await apiClient.get(`/api/canvas-sim/pre-check/${courseId}/${quizId}`, { headers });
    return resp.data;
  } catch (error: unknown) {
    const err = error as { response?: { data?: { detail?: string } }; message?: string };
    return {
      success: false,
      access_code_required: false,
      warnings: [],
      error: err.response?.data?.detail || err.message || 'Pre-check failed',
    };
  }
}

export async function createTestStudent(
  name: string,
  email: string,
  accountId: number = 1,
): Promise<{ success: boolean; test_student?: TestStudent; error?: string }> {
  try {
    const headers = await getCanvasHeaders();
    const resp = await apiClient.post(
      '/api/canvas-sim/test-students',
      { name, email, account_id: accountId },
      { headers },
    );
    return resp.data;
  } catch (error: unknown) {
    const err = error as { response?: { data?: { detail?: string } }; message?: string };
    return { success: false, error: err.response?.data?.detail || err.message || 'Failed' };
  }
}

export async function listTestStudents(): Promise<{
  success: boolean;
  test_students: TestStudent[];
  total: number;
  error?: string;
}> {
  try {
    // Canvas headers are optional for listing (only used to filter by domain)
    let headers: Record<string, string> = {};
    try {
      headers = await getCanvasHeaders();
    } catch {
      // No Canvas token yet — still list local test students
    }
    const resp = await apiClient.get('/api/canvas-sim/test-students', { headers });
    return resp.data;
  } catch (error: unknown) {
    const err = error as { response?: { status?: number; data?: { detail?: string } }; message?: string };
    // If 401, the user is not logged in (JWT missing)
    if (err.response?.status === 401) {
      return { success: false, test_students: [], total: 0, error: 'Chưa đăng nhập hoặc phiên hết hạn' };
    }
    return { success: false, test_students: [], total: 0, error: err.response?.data?.detail || err.message || 'Failed to list test students' };
  }
}

export async function deleteTestStudent(id: string): Promise<{ success: boolean; error?: string }> {
  try {
    const headers = await getCanvasHeaders();
    const resp = await apiClient.delete(`/api/canvas-sim/test-students/${id}`, { headers });
    return resp.data;
  } catch (error: unknown) {
    const err = error as { response?: { data?: { detail?: string } }; message?: string };
    return { success: false, error: err.response?.data?.detail || err.message || 'Failed' };
  }
}

export async function executeSimulation(
  req: SimulationExecuteRequest,
): Promise<{
  success: boolean;
  run_id?: string;
  score?: number | null;
  kept_score?: number | null;
  points_possible?: number | null;
  canvas_submission_id?: number;
  attempt?: number;
  status?: string;
  error?: string;
}> {
  try {
    const headers = await getCanvasHeaders();
    const resp = await apiClient.post('/api/canvas-sim/execute', req, { headers, timeout: 120000 });
    return resp.data;
  } catch (error: unknown) {
    const err = error as { response?: { data?: { detail?: string } }; message?: string };
    return { success: false, error: err.response?.data?.detail || err.message || 'Simulation failed' };
  }
}

export async function executeBatchSimulation(
  req: SimulationBatchRequest,
): Promise<{
  success: boolean;
  total?: number;
  succeeded?: number;
  failed?: number;
  results?: Array<Record<string, unknown>>;
  error?: string;
}> {
  try {
    const headers = await getCanvasHeaders();
    const resp = await apiClient.post('/api/canvas-sim/execute-batch', req, { headers, timeout: 300000 });
    return resp.data;
  } catch (error: unknown) {
    const err = error as { response?: { data?: { detail?: string } }; message?: string };
    return { success: false, error: err.response?.data?.detail || err.message || 'Batch failed' };
  }
}

export async function getSimulationHistory(
  courseId?: number,
  quizId?: number,
  limit: number = 50,
): Promise<{ success: boolean; runs: SimulationRunResult[]; total: number }> {
  try {
    const headers = await getCanvasHeaders();
    const params: Record<string, unknown> = { limit };
    if (courseId) params.course_id = courseId;
    if (quizId) params.quiz_id = quizId;
    const resp = await apiClient.get('/api/canvas-sim/history', { headers, params });
    return resp.data;
  } catch {
    return { success: false, runs: [], total: 0 };
  }
}

export async function getAuditLog(limit: number = 100): Promise<{
  success: boolean;
  logs: AuditLogEntry[];
  total: number;
}> {
  try {
    const headers = await getCanvasHeaders();
    const resp = await apiClient.get('/api/canvas-sim/audit-log', { headers, params: { limit } });
    return resp.data;
  } catch {
    return { success: false, logs: [], total: 0 };
  }
}

export const canvasSimApi = {
  preCheckQuiz,
  createTestStudent,
  listTestStudents,
  deleteTestStudent,
  executeSimulation,
  executeBatchSimulation,
  getSimulationHistory,
  getAuditLog,
};

export default canvasSimApi;
