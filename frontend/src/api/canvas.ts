// ============================================================================
// Canvas LMS API Service
// ============================================================================

import { apiClient } from './client';
import { getCanvasToken, getCanvasBaseUrl } from '../utils/canvasStorage';
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
 * Get headers with Canvas token for proxy requests
 */
function getCanvasHeaders(): Record<string, string> {
  const token = getCanvasToken();
  const baseUrl = getCanvasBaseUrl();
  
  if (!token) {
    throw new Error('Canvas access token not configured');
  }
  
  return {
    'X-Canvas-Token': token,
    'X-Canvas-Base-Url': baseUrl,
  };
}

/**
 * Fetch user's courses from Canvas
 */
export async function fetchCourses(): Promise<CanvasCoursesResponse> {
  try {
    const response = await apiClient.get<CanvasCoursesResponse>(
      '/api/canvas/courses',
      { headers: getCanvasHeaders() }
    );
    return response.data;
  } catch (error: unknown) {
    const err = error as { response?: { data?: { error?: string }; status?: number } };
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
      error: err.response?.data?.error || 'Failed to fetch courses',
    };
  }
}

/**
 * Fetch files from a specific course
 */
export async function fetchCourseFiles(courseId: number): Promise<CanvasFilesResponse> {
  try {
    const response = await apiClient.get<CanvasFilesResponse>(
      `/api/canvas/courses/${courseId}/files`,
      { headers: getCanvasHeaders() }
    );
    return response.data;
  } catch (error: unknown) {
    const err = error as { response?: { data?: { error?: string }; status?: number } };
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
      error: err.response?.data?.error || 'Failed to fetch files',
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
    const response = await apiClient.post<FileDownloadResponse>(
      '/api/canvas/download',
      request,
      { headers: getCanvasHeaders() }
    );
    return response.data;
  } catch (error: unknown) {
    const err = error as { response?: { data?: { error?: string } } };
    return {
      success: false,
      file_id: request.file_id,
      filename: request.filename,
      status: 'failed',
      error: err.response?.data?.error || 'Download failed',
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
    const response = await apiClient.post<BatchDownloadResponse>(
      '/api/canvas/download/batch',
      request,
      { 
        headers: getCanvasHeaders(),
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
    const response = await apiClient.post<QTIImportResponse>(
      '/api/canvas/import-qti-bank',
      request,
      { 
        headers: getCanvasHeaders(),
        timeout: 300000, // 5 minutes for full import process
      }
    );
    return response.data;
  } catch (error: unknown) {
    const err = error as { response?: { data?: { error?: string; detail?: string }; status?: number } };
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
      error: err.response?.data?.error || err.response?.data?.detail || 'Failed to import QTI to Canvas',
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
};

export default canvasApi;
