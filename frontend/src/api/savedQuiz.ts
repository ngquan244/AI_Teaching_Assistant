// ============================================================================
// Saved Quiz API Service
// ============================================================================

import { apiClient } from './client';
import type {
  SavedQuiz,
  SavedQuizDetail,
  SavedQuizListResponse,
  SavedQuizCreateRequest,
  SavedQuizUpdateRequest,
  SavedQuizQuestionCreate,
  CourseGroup,
} from '../types/savedQuiz';

const BASE = '/api/saved-quizzes';

// ---- List (paginated + filtered) ----

export async function listSavedQuizzes(params: {
  page?: number;
  page_size?: number;
  course_id?: number | null;
  search?: string;
  difficulty?: string;
  starred?: boolean;
  sort?: string;
} = {}): Promise<SavedQuizListResponse> {
  const query: Record<string, string | number | boolean> = {};
  if (params.page) query.page = params.page;
  if (params.page_size) query.page_size = params.page_size;
  if (params.course_id != null) query.course_id = params.course_id;
  if (params.search) query.search = params.search;
  if (params.difficulty) query.difficulty = params.difficulty;
  if (params.starred != null) query.starred = params.starred;
  if (params.sort) query.sort = params.sort;

  const res = await apiClient.get<SavedQuizListResponse>(BASE, { params: query });
  return res.data;
}

// ---- Get detail ----

export async function getSavedQuiz(quizId: string): Promise<SavedQuizDetail> {
  const res = await apiClient.get<SavedQuizDetail>(`${BASE}/${quizId}`);
  return res.data;
}

// ---- Create ----

export async function createSavedQuiz(data: SavedQuizCreateRequest): Promise<SavedQuizDetail> {
  const res = await apiClient.post<SavedQuizDetail>(BASE, data);
  return res.data;
}

// ---- Update metadata ----

export async function updateSavedQuiz(quizId: string, data: SavedQuizUpdateRequest): Promise<SavedQuiz> {
  const res = await apiClient.put<SavedQuiz>(`${BASE}/${quizId}`, data);
  return res.data;
}

// ---- Delete ----

export async function deleteSavedQuiz(quizId: string): Promise<void> {
  await apiClient.delete(`${BASE}/${quizId}`);
}

// ---- Toggle star ----

export async function toggleStar(quizId: string): Promise<SavedQuiz> {
  const res = await apiClient.patch<SavedQuiz>(`${BASE}/${quizId}/star`);
  return res.data;
}

// ---- Duplicate ----

export async function duplicateSavedQuiz(quizId: string): Promise<SavedQuizDetail> {
  const res = await apiClient.post<SavedQuizDetail>(`${BASE}/${quizId}/duplicate`);
  return res.data;
}

// ---- Bulk replace questions ----

export async function replaceQuestions(
  quizId: string,
  questions: SavedQuizQuestionCreate[],
): Promise<SavedQuizDetail> {
  const res = await apiClient.put<SavedQuizDetail>(`${BASE}/${quizId}/questions`, questions);
  return res.data;
}

// ---- Course groups ----

export async function getCourseGroups(): Promise<CourseGroup[]> {
  const res = await apiClient.get<CourseGroup[]>(`${BASE}/courses`);
  return res.data;
}

// Grouped export
export const savedQuizApi = {
  list: listSavedQuizzes,
  get: getSavedQuiz,
  create: createSavedQuiz,
  update: updateSavedQuiz,
  delete: deleteSavedQuiz,
  toggleStar,
  duplicate: duplicateSavedQuiz,
  replaceQuestions,
  getCourseGroups,
};
