// ============================================================================
// Canvas LMS API Service
// ============================================================================

import { apiClient } from './client';
import { authApi } from './auth';
import type {
  CanvasCoursesResponse,
  CanvasFilesResponse,
  FileDownloadRequest,
  FileDownloadResponse,
  BatchDownloadRequest,
  BatchDownloadResponse,
  QTIImportRequest,
  QTIImportResponse,
} from '../types/canvas';

// Cache for Canvas token to avoid repeated API calls
let cachedToken: { token: string; baseUrl: string; expiresAt: number } | null = null;

/**
 * Get Canvas headers from backend (fetches decrypted token)
 * Caches the token for 5 minutes to reduce API calls
 * Exported so canvasQuiz.ts can share the same cache.
 */
export async function getCanvasHeaders(): Promise<Record<string, string>> {
  const now = Date.now();
  
  // Return cached token if still valid
  if (cachedToken && cachedToken.expiresAt > now) {
    return {
      'X-Canvas-Token': cachedToken.token,
      'X-Canvas-Base-Url': cachedToken.baseUrl,
    };
  }

  try {
    const { access_token, canvas_domain } = await authApi.getActiveCanvasToken();
    
    // Cache for 5 minutes
    cachedToken = {
      token: access_token,
      baseUrl: canvas_domain,
      expiresAt: now + 5 * 60 * 1000,
    };

    return {
      'X-Canvas-Token': access_token,
      'X-Canvas-Base-Url': canvas_domain,
    };
  } catch {
    throw new Error('Canvas access token not configured. Please add a token in Settings.');
  }
}

/**
 * Clear the cached Canvas token (call when token is updated)
 */
export function clearCanvasTokenCache(): void {
  cachedToken = null;
}

/**
 * Fetch user's courses from Canvas
 */
export async function fetchCourses(): Promise<CanvasCoursesResponse> {
  try {
    const headers = await getCanvasHeaders();
    const response = await apiClient.get<CanvasCoursesResponse>(
      '/api/canvas/courses',
      { headers }
    );
    return response.data;
  } catch (error: unknown) {
    const err = error as { response?: { data?: { error?: string }; status?: number }; message?: string };
    if (err.response?.status === 401) {
      return {
        success: false,
        courses: [],
        error: 'Invalid or expired Canvas access token',
      };
    }
    return {
      success: false,
      courses: [],
      error: err.response?.data?.error || err.message || 'Failed to fetch courses',
    };
  }
}

/**
 * Fetch files from a specific course
 */
export async function fetchCourseFiles(courseId: number): Promise<CanvasFilesResponse> {
  try {
    const headers = await getCanvasHeaders();
    const response = await apiClient.get<CanvasFilesResponse>(
      `/api/canvas/courses/${courseId}/files`,
      { headers }
    );
    return response.data;
  } catch (error: unknown) {
    const err = error as { response?: { data?: { error?: string }; status?: number }; message?: string };
    if (err.response?.status === 401) {
      return {
        success: false,
        files: [],
        course_id: courseId,
        error: 'Invalid or expired Canvas access token',
      };
    }
    return {
      success: false,
      files: [],
      course_id: courseId,
      error: err.response?.data?.error || err.message || 'Failed to fetch files',
    };
  }
}

/**
 * Download a single file with MD5 deduplication
 */
export async function downloadFile(
  request: FileDownloadRequest
): Promise<FileDownloadResponse> {
  try {
    const headers = await getCanvasHeaders();
    const response = await apiClient.post<FileDownloadResponse>(
      '/api/canvas/download',
      request,
      { headers }
    );
    return response.data;
  } catch (error: unknown) {
    const err = error as { response?: { data?: { error?: string } }; message?: string };
    return {
      success: false,
      file_id: request.file_id,
      filename: request.filename,
      status: 'failed',
      error: err.response?.data?.error || err.message || 'Download failed',
    };
  }
}

/**
 * Download multiple files with MD5 deduplication
 */
export async function downloadFiles(
  request: BatchDownloadRequest
): Promise<BatchDownloadResponse> {
  try {
    const headers = await getCanvasHeaders();
    const response = await apiClient.post<BatchDownloadResponse>(
      '/api/canvas/download/batch',
      request,
      { 
        headers,
        timeout: 300000, // 5 minutes for batch downloads
      }
    );
    return response.data;
  } catch {
    return {
      success: false,
      results: [],
      total: request.files.length,
      saved: 0,
      duplicates: 0,
      failed: request.files.length,
    };
  }
}

/**
 * Stream download a single file (for progress tracking)
 * Returns an async generator that yields download progress
 */
export async function* downloadFileWithProgress(
  request: FileDownloadRequest,
  _onProgress?: (progress: number) => void
): AsyncGenerator<FileDownloadResponse> {
  // Initial status: queued
  yield {
    success: true,
    file_id: request.file_id,
    filename: request.filename,
    status: 'queued',
  };

  // Status: downloading
  yield {
    success: true,
    file_id: request.file_id,
    filename: request.filename,
    status: 'downloading',
  };

  try {
    const result = await downloadFile(request);
    yield result;
  } catch (error) {
    yield {
      success: false,
      file_id: request.file_id,
      filename: request.filename,
      status: 'failed',
      error: 'Download failed',
    };
  }
}

/**
 * Import QTI zip file into Canvas as a new Question Bank
 * Uses Content Migration API flow
 */
export async function importQTIToCanvas(
  request: QTIImportRequest
): Promise<QTIImportResponse> {
  try {
    const headers = await getCanvasHeaders();
    const response = await apiClient.post<QTIImportResponse>(
      '/api/canvas/import-qti-bank',
      request,
      { 
        headers,
        timeout: 300000, // 5 minutes for full import process
      }
    );
    return response.data;
  } catch (error: unknown) {
    const err = error as { response?: { data?: { error?: string; detail?: string }; status?: number }; message?: string };
    if (err.response?.status === 401) {
      return {
        success: false,
        status: 'failed',
        error: 'Invalid or expired Canvas access token',
      };
    }
    return {
      success: false,
      status: 'failed',
      error: err.response?.data?.error || err.response?.data?.detail || err.message || 'Failed to import QTI to Canvas',
    };
  }
}

export const canvasApi = {
  fetchCourses,
  fetchCourseFiles,
  downloadFile,
  downloadFiles,
  downloadFileWithProgress,
  importQTIToCanvas,
  clearCanvasTokenCache,
};

export default canvasApi;
