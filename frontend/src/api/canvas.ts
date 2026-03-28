// ============================================================================
// Canvas LMS API Service
// ============================================================================

import { apiClient } from './client';
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

/**
 * Legacy helper kept for transition compatibility.
 * Canvas tokens are now resolved server-side, so no custom headers are sent.
 */
export async function getCanvasHeaders(): Promise<Record<string, string>> {
  return {};
}

/**
 * No-op legacy cache clearer.
 */
export function clearCanvasTokenCache(): void {}

export async function fetchCourses(): Promise<CanvasCoursesResponse> {
  try {
    const response = await apiClient.get<CanvasCoursesResponse>('/api/canvas/courses');
    return response.data;
  } catch (error: unknown) {
    const err = error as { response?: { data?: { detail?: string; error?: string }; status?: number }; message?: string };
    if (err.response?.status === 401) {
      return {
        success: false,
        courses: [],
        error: err.response?.data?.detail || 'Canvas access token not configured',
      };
    }
    return {
      success: false,
      courses: [],
      error: err.response?.data?.detail || err.response?.data?.error || err.message || 'Failed to fetch courses',
    };
  }
}

export async function fetchCourseFiles(courseId: number): Promise<CanvasFilesResponse> {
  try {
    const response = await apiClient.get<CanvasFilesResponse>(
      `/api/canvas/courses/${courseId}/files`,
    );
    return response.data;
  } catch (error: unknown) {
    const err = error as { response?: { data?: { detail?: string; error?: string }; status?: number }; message?: string };
    return {
      success: false,
      files: [],
      course_id: courseId,
      error: err.response?.data?.detail || err.response?.data?.error || err.message || 'Failed to fetch files',
    };
  }
}

export async function downloadFile(
  request: FileDownloadRequest
): Promise<FileDownloadResponse> {
  try {
    const response = await apiClient.post<FileDownloadResponse>(
      '/api/canvas/download',
      request,
    );
    return response.data;
  } catch (error: unknown) {
    const err = error as { response?: { data?: { detail?: string; error?: string } }; message?: string };
    return {
      success: false,
      file_id: request.file_id,
      filename: request.filename,
      status: 'failed',
      error: err.response?.data?.detail || err.response?.data?.error || err.message || 'Download failed',
    };
  }
}

export async function downloadFiles(
  request: BatchDownloadRequest
): Promise<BatchDownloadResponse> {
  try {
    const response = await apiClient.post<BatchDownloadResponse>(
      '/api/canvas/download/batch',
      request,
      {
        timeout: 300000,
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

export async function* downloadFileWithProgress(
  request: FileDownloadRequest,
  _onProgress?: (progress: number) => void
): AsyncGenerator<FileDownloadResponse> {
  yield {
    success: true,
    file_id: request.file_id,
    filename: request.filename,
    status: 'queued',
  };

  yield {
    success: true,
    file_id: request.file_id,
    filename: request.filename,
    status: 'downloading',
  };

  try {
    const result = await downloadFile(request);
    yield result;
  } catch {
    yield {
      success: false,
      file_id: request.file_id,
      filename: request.filename,
      status: 'failed',
      error: 'Download failed',
    };
  }
}

export async function importQTIToCanvas(
  request: QTIImportRequest
): Promise<QTIImportResponse> {
  try {
    const response = await apiClient.post<QTIImportResponse>(
      '/api/canvas/import-qti-bank',
      request,
      { timeout: 120000 }
    );
    return response.data;
  } catch (error: unknown) {
    const err = error as { response?: { data?: { detail?: string; error?: string } }; message?: string };
    return {
      success: false,
      status: 'failed',
      error: err.response?.data?.detail || err.response?.data?.error || err.message || 'Failed to import QTI package',
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
  getCanvasHeaders,
};

export default canvasApi;
