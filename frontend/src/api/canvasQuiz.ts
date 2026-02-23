// ============================================================================
// Canvas Quiz Builder API Service
// ============================================================================

import { apiClient } from './client';
import { getCanvasHeaders } from './canvas';   // shared token cache
import type {
  CanvasQuiz,
  CreateCanvasQuizRequest,
  CreateCanvasQuizResponse,
} from '../types/canvas';

// ---- Quizzes ----

export async function fetchQuizzes(courseId: number): Promise<{
  success: boolean;
  quizzes: CanvasQuiz[];
  error?: string;
}> {
  try {
    const headers = await getCanvasHeaders();
    const response = await apiClient.get(
      `/api/canvas-quiz/courses/${courseId}/quizzes`,
      { headers },
    );
    return response.data;
  } catch (error: unknown) {
    const err = error as { response?: { data?: { detail?: string } }; message?: string };
    return {
      success: false,
      quizzes: [],
      error: err.response?.data?.detail || err.message || 'Failed to fetch quizzes',
    };
  }
}

// ---- Quiz Questions ----

export async function fetchQuizQuestions(courseId: number, quizId: number): Promise<{
  success: boolean;
  questions: Array<Record<string, unknown>>;
  total?: number;
  error?: string;
}> {
  try {
    const headers = await getCanvasHeaders();
    const response = await apiClient.get(
      `/api/canvas-quiz/courses/${courseId}/quizzes/${quizId}/questions`,
      { headers },
    );
    return response.data;
  } catch (error: unknown) {
    const err = error as { response?: { data?: { detail?: string } }; message?: string };
    return {
      success: false,
      questions: [],
      error: err.response?.data?.detail || err.message || 'Failed to fetch quiz questions',
    };
  }
}

// ---- Create Quiz (end-to-end) ----

export async function createFullQuiz(
  request: CreateCanvasQuizRequest,
): Promise<CreateCanvasQuizResponse> {
  try {
    const headers = await getCanvasHeaders();
    const response = await apiClient.post<CreateCanvasQuizResponse>(
      '/api/canvas-quiz/create-quiz',
      request,
      { headers, timeout: 120000 },
    );
    return response.data;
  } catch (error: unknown) {
    const err = error as { response?: { data?: { detail?: string; error?: string } }; message?: string };
    return {
      success: false,
      error: err.response?.data?.detail || err.response?.data?.error || err.message || 'Failed to create quiz',
    };
  }
}

export const canvasQuizApi = {
  fetchQuizzes,
  fetchQuizQuestions,
  createFullQuiz,
};

export default canvasQuizApi;
