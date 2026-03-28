/**
 * Canvas RAG API
 * API calls for Canvas-specific document RAG operations
 * Completely separate from uploaded document RAG
 */

import { apiClient } from './client';
import { getCanvasHeaders, clearCanvasTokenCache } from './canvas';

const API_BASE = '/api/canvas-rag';

// Re-export clearCanvasTokenCache for convenience
export { clearCanvasTokenCache as clearCanvasRagTokenCache };

// ===== Error Types =====

/**
 * Thrown when the current Canvas token lacks access to a course.
 * The UI should show a clear message rather than a generic error.
 */
export class CanvasPermissionError extends Error {
  constructor(message: string) {
    super(message);
    this.name = 'CanvasPermissionError';
  }
}

// ===== Helpers =====

/**
 * Build an axios config that includes Canvas permission headers.
 * If the user has no Canvas token configured, the request is sent
 * WITHOUT Canvas headers — the backend will deny access to
 * course-scoped data (not fail-open).
 */
async function canvasConfig(
  extra?: Record<string, unknown>,
): Promise<Record<string, unknown>> {
  try {
    const headers = await getCanvasHeaders();
    return { ...extra, headers: { ...headers, ...(extra as any)?.headers } };
  } catch {
    // No Canvas token configured → send without headers.
    // The backend will exclude course-scoped data appropriately.
    return extra ?? {};
  }
}

/**
 * Intercept 403 from canvas-rag endpoints and throw CanvasPermissionError.
 */
function handlePermissionError(error: unknown): never {
  if (
    typeof error === 'object' &&
    error !== null &&
    'response' in error
  ) {
    const resp = (error as any).response;
    if (resp?.status === 403) {
      const detail = resp?.data?.detail || 'Canvas token does not have access to this course.';
      throw new CanvasPermissionError(detail);
    }
  }
  throw error;
}

// ===== Types =====

export interface CanvasDownloadRequest {
  url: string;
  filename: string;
  course_id: number;
  file_id: number;
}

export interface CanvasDownloadResponse {
  success: boolean;
  status: 'saved' | 'duplicate' | 'failed';
  md5_hash?: string;
  filename?: string;
  file_path?: string;
  existing_filename?: string;
  message?: string;
  error?: string;
}

export interface CanvasIndexRequest {
  filename: string;
  course_id?: number;  // Canvas course ID for collection naming
}

export interface CanvasIndexResponse {
  success: boolean;
  message?: string;
  file_hash?: string;
  filename?: string;
  pages_loaded?: number;
  chunks_added?: number;
  already_indexed?: boolean;
  topics_extracted?: number;
  topics?: Array<{ name: string; description: string }>;
  error?: string;
}

export interface CanvasExtractTopicsRequest {
  filename: string;
  num_topics?: number;
}

export interface CanvasTopicsResponse {
  success: boolean;
  topics: string[];
  filename: string;
  error?: string;
}

export interface CanvasUpdateTopicsRequest {
  filename: string;
  topics: string[];
}

export interface CanvasFile {
  filename: string;
  size: number;
  modified: number;
  is_indexed: boolean;
}

export interface CanvasIndexedDocument {
  filename: string;
  original_filename: string;
  file_hash: string;
  indexed_at: string;
  chunks_added: number;
  topic_count: number;
  course_id?: number;
  course_name?: string;
}

export interface CanvasIndexedDocumentsListResponse {
  success: boolean;
  documents: CanvasIndexedDocument[];
  total: number;
  page: number;
  page_size: number;
  pages: number;
}

export interface CanvasStats {
  total_documents: number;
  total_chunks: number;
  collection_name: string;
  unique_files: number;
}

export interface CanvasQueryRequest {
  question: string;
  k?: number;
  return_context?: boolean;
  selected_documents?: string[];
}

export interface CanvasQueryResponse {
  success: boolean;
  answer?: string;
  sources?: Array<{
    content: string;
    source: string;
    page?: number;
    score?: number;
  }>;
  context?: string;
  error?: string;
}

export interface CanvasQuizRequest {
  topics: string[];
  num_questions?: number;
  difficulty?: 'easy' | 'medium' | 'hard';
  language?: 'vi' | 'en';
  k?: number;
  selected_documents?: string[];
}

export interface CanvasQuizQuestion {
  question_number: number;
  question: string;
  options: {
    A: string;
    B: string;
    C: string;
    D: string;
  };
  correct_answer: string;
}

export interface CanvasQuizResponse {
  success: boolean;
  questions: CanvasQuizQuestion[];
  topic?: string;
  error?: string;
}

// ===== API Functions =====

/**
 * Download a file from Canvas with MD5 deduplication
 */
export async function downloadCanvasFile(
  request: CanvasDownloadRequest
): Promise<CanvasDownloadResponse> {
  const headers = await getCanvasHeaders();
  const response = await apiClient.post<CanvasDownloadResponse>(
    `${API_BASE}/download`,
    request,
    { headers }
  );
  return response.data;
}

/**
 * Index a downloaded Canvas file
 */
export async function indexCanvasFile(
  filename: string,
  courseId?: number
): Promise<CanvasIndexResponse> {
  try {
    const cfg = await canvasConfig();
    const response = await apiClient.post<CanvasIndexResponse>(
      `${API_BASE}/index`,
      { filename, course_id: courseId },
      cfg,
    );
    return response.data;
  } catch (error) {
    handlePermissionError(error);
  }
}

/**
 * Extract topics from a Canvas file
 */
export async function extractCanvasTopics(
  filename: string,
  numTopics: number = 8
): Promise<CanvasTopicsResponse> {
  try {
    const cfg = await canvasConfig();
    const response = await apiClient.post<CanvasTopicsResponse>(
      `${API_BASE}/extract-topics`,
      { filename, num_topics: numTopics },
      cfg,
    );
    return response.data;
  } catch (error) {
    handlePermissionError(error);
  }
}

/**
 * Get topics for a Canvas document
 */
export async function getCanvasDocumentTopics(
  filename: string
): Promise<CanvasTopicsResponse> {
  try {
    const cfg = await canvasConfig();
    const response = await apiClient.get<CanvasTopicsResponse>(
      `${API_BASE}/topics/${encodeURIComponent(filename)}`,
      cfg,
    );
    return response.data;
  } catch (error) {
    handlePermissionError(error);
  }
}

/**
 * Update topics for a Canvas document
 */
export async function updateCanvasDocumentTopics(
  filename: string,
  topics: string[]
): Promise<{ success: boolean; message?: string }> {
  try {
    const cfg = await canvasConfig();
    const response = await apiClient.put(
      `${API_BASE}/topics`,
      { filename, topics },
      cfg,
    );
    return response.data;
  } catch (error) {
    handlePermissionError(error);
  }
}

/**
 * List indexed Canvas documents (paginated)
 * Optionally filter by courseId
 * Sends Canvas headers so backend can validate course access.
 */
export async function listIndexedCanvasDocuments(courseId?: number, page = 1, pageSize = 10): Promise<{
  success: boolean;
  documents: CanvasIndexedDocument[];
  total: number;
  page: number;
  page_size: number;
  pages: number;
}> {
  try {
    const params: Record<string, unknown> = { page, page_size: pageSize };
    if (courseId) params.course_id = courseId;
    const cfg = await canvasConfig({ params });
    const response = await apiClient.get<CanvasIndexedDocumentsListResponse>(`${API_BASE}/indexed`, cfg);
    return response.data;
  } catch (error) {
    handlePermissionError(error);
  }
}

/**
 * List all indexed Canvas documents for a course by walking pagination.
 * Useful when the UI needs authoritative indexed status for every remote file.
 */
export async function listAllIndexedCanvasDocuments(
  courseId?: number,
): Promise<CanvasIndexedDocument[]> {
  const pageSize = 100;
  const firstPage = await listIndexedCanvasDocuments(courseId, 1, pageSize);

  if (!firstPage.success || firstPage.pages <= 1) {
    return firstPage.documents;
  }

  const remainingPages = Array.from(
    { length: firstPage.pages - 1 },
    (_, index) => index + 2,
  );

  const responses = await Promise.all(
    remainingPages.map((page) => listIndexedCanvasDocuments(courseId, page, pageSize)),
  );

  return [
    ...firstPage.documents,
    ...responses.flatMap((response) => response.documents),
  ];
}

/**
 * Query Canvas documents
 */
export async function queryCanvasDocuments(
  request: CanvasQueryRequest
): Promise<CanvasQueryResponse> {
  try {
    const cfg = await canvasConfig();
    const response = await apiClient.post<CanvasQueryResponse>(
      `${API_BASE}/query`,
      request,
      cfg,
    );
    return response.data;
  } catch (error) {
    handlePermissionError(error);
  }
}

/**
 * Generate quiz from Canvas documents
 */
export async function generateCanvasQuiz(
  request: CanvasQuizRequest
): Promise<CanvasQuizResponse> {
  try {
    const cfg = await canvasConfig();
    const response = await apiClient.post<CanvasQuizResponse>(
      `${API_BASE}/generate-quiz`,
      request,
      cfg,
    );
    return response.data;
  } catch (error) {
    handlePermissionError(error);
  }
}

/**
 * Reset Canvas index
 */
export async function resetCanvasIndex(): Promise<{
  success: boolean;
  message?: string;
}> {
  const response = await apiClient.post(`${API_BASE}/reset`);
  return response.data;
}

/**
 * Remove index for a Canvas file (keep the file)
 */
export async function removeCanvasFileIndex(
  filename: string
): Promise<{ success: boolean; message?: string }> {
  const response = await apiClient.delete(
    `${API_BASE}/index/${encodeURIComponent(filename)}`
  );
  return response.data;
}

// ===== Async (Celery) API Functions =====

import type { AsyncJobResponse } from './jobs';

/**
 * Generate quiz from Canvas documents asynchronously via Celery.
 */
export async function asyncCanvasGenerateQuiz(
  request: CanvasQuizRequest,
): Promise<AsyncJobResponse> {
  try {
    const cfg = await canvasConfig();
    const response = await apiClient.post<AsyncJobResponse>(
      `${API_BASE}/async/generate-quiz`,
      request,
      cfg,
    );
    return response.data;
  } catch (error) {
    handlePermissionError(error);
  }
}

/**
 * Index a downloaded Canvas file asynchronously via Celery.
 */
export async function asyncIndexCanvasFile(
  filename: string,
  courseId?: number,
): Promise<AsyncJobResponse> {
  try {
    const cfg = await canvasConfig();
    const response = await apiClient.post<AsyncJobResponse>(
      `${API_BASE}/async/index`,
      { filename, course_id: courseId },
      cfg,
    );
    return response.data;
  } catch (error) {
    handlePermissionError(error);
  }
}

export const canvasRagApi = {
  downloadCanvasFile,
  indexCanvasFile,
  extractCanvasTopics,
  getCanvasDocumentTopics,
  updateCanvasDocumentTopics,
  listIndexedCanvasDocuments,
  listAllIndexedCanvasDocuments,
  queryCanvasDocuments,
  generateCanvasQuiz,
  resetCanvasIndex,
  removeCanvasFileIndex,
  asyncCanvasGenerateQuiz,
  asyncIndexCanvasFile,
};

export default canvasRagApi;
