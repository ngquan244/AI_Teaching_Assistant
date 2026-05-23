// ============================================================================
// Canvas Student Import API Service
// ============================================================================
//
// Wraps the /api/canvas/students/import endpoints (preview / confirm /
// batches / template). Auth is attached automatically by apiClient.

import { apiClient, getStoredToken } from './client';

// ---- Types ----

export type ImportMode = 'create' | 'enroll';

export type BatchStatus = 'preview' | 'confirmed' | 'failed' | 'expired';

export type RowStatus =
  // shared
  | 'invalid'
  | 'duplicate_in_file'
  | 'skipped'
  | 'failed'
  // create-mode
  | 'existed_in_db'
  | 'existed_on_canvas'
  | 'synced_from_canvas'
  | 'valid_new_user'
  | 'created'
  | 'old_account_exists'   // old {MSSV}@vnu.edu.vn on Canvas; will create sv-email
  | 'stale_old_account'    // DB has old entry; will create sv-email
  // enroll-mode
  | 'user_not_found_on_canvas'
  | 'enroll_ready'
  | 'already_enrolled'
  | 'enrollment_inactive'
  | 'enrollment_completed'
  | 'enrollment_deleted'
  | 'enrolled'
  | 'enrollment_failed';

export interface ImportRow {
  id: string;
  row_number: number;
  student_code: string | null;
  full_name: string | null;
  generated_email: string | null;
  status: RowStatus;
  canvas_user_id: number | null;
  canvas_enrollment_id: number | null;
  canvas_student_id: string | null;
  sis_user_id_used: string | null;
  error_code: string | null;
  message: string | null;
  created_in_this_batch: boolean;
  initial_password: string | null; // populated iff created_in_this_batch; not stored in DB
}

export interface ImportBatch {
  id: string;
  owner_id: string;
  canvas_domain: string;
  account_id: number;
  course_id: number | null;
  mode: ImportMode;
  filename: string | null;
  status: BatchStatus;
  total_rows: number;
  summary: Record<string, number> | null;
  enroll_after_create: boolean;
  enroll_existing: boolean;
  expires_at: string | null;
  created_at: string | null;
  confirmed_at: string | null;
  rows: ImportRow[];
}

export interface PreviewParams {
  file: File;
  mode: ImportMode;
  account_id?: number;
  course_id?: number | null;
  enroll_after_create?: boolean;
  enroll_existing?: boolean;
  canvas_domain_hint?: string;
}

export interface ConfirmParams {
  batch_id: string;
  enroll_after_create?: boolean;
  enroll_existing?: boolean;
  reactivate_inactive?: boolean;
  recreate_deleted?: boolean;
}

export interface ImportApiResult<T> {
  success: boolean;
  data?: T;
  error?: string;
  error_code?: string;
  http_status?: number;
}

// ---- Helpers ----

function extractError(error: unknown): { message: string; code?: string; status?: number; batch?: ImportBatch } {
  const err = error as {
    response?: { status?: number; data?: { detail?: unknown } };
    message?: string;
  };
  const detail = err.response?.data?.detail;
  const status = err.response?.status;

  if (detail && typeof detail === 'object') {
    const d = detail as { error_code?: string; status?: string; batch?: ImportBatch };
    return {
      message: d.error_code || d.status || 'Lỗi không xác định.',
      code: d.error_code,
      status,
      batch: d.batch,
    };
  }
  if (typeof detail === 'string') {
    return { message: detail, status };
  }
  return { message: err.message || 'Lỗi không xác định.', status };
}

// ---- API Functions ----

export async function previewImport(
  params: PreviewParams,
): Promise<ImportApiResult<ImportBatch>> {
  const fd = new FormData();
  fd.append('file', params.file);
  fd.append('mode', params.mode);
  fd.append('account_id', String(params.account_id ?? 1));
  if (params.course_id != null) fd.append('course_id', String(params.course_id));
  fd.append('enroll_after_create', String(!!params.enroll_after_create));
  fd.append('enroll_existing', String(!!params.enroll_existing));
  if (params.canvas_domain_hint) fd.append('canvas_domain_hint', params.canvas_domain_hint);

  try {
    const resp = await apiClient.post<ImportBatch>(
      '/api/canvas/students/import/preview',
      fd,
      {
        headers: { 'Content-Type': 'multipart/form-data' },
        timeout: 180000,
      },
    );
    return { success: true, data: resp.data };
  } catch (error: unknown) {
    const e = extractError(error);
    return { success: false, error: e.message, error_code: e.code, http_status: e.status };
  }
}

export async function confirmImport(
  params: ConfirmParams,
): Promise<ImportApiResult<ImportBatch> & { already_confirmed?: boolean }> {
  try {
    const resp = await apiClient.post<ImportBatch>(
      '/api/canvas/students/import/confirm',
      params,
      { timeout: 600000 },
    );
    return { success: true, data: resp.data };
  } catch (error: unknown) {
    const e = extractError(error);
    // 409 + BATCH_ALREADY_CONFIRMED → return the batch as success-ish so the
    // UI can re-render the confirmed state.
    if (e.code === 'BATCH_ALREADY_CONFIRMED' && e.batch) {
      return {
        success: true,
        data: e.batch,
        already_confirmed: true,
        error_code: e.code,
      };
    }
    return { success: false, error: e.message, error_code: e.code, http_status: e.status };
  }
}

export async function getBatch(batchId: string): Promise<ImportApiResult<ImportBatch>> {
  try {
    const resp = await apiClient.get<ImportBatch>(
      `/api/canvas/students/import/batches/${batchId}`,
    );
    return { success: true, data: resp.data };
  } catch (error: unknown) {
    const e = extractError(error);
    return { success: false, error: e.message, error_code: e.code, http_status: e.status };
  }
}

/**
 * Download the blank Excel template. Triggers a browser save dialog.
 */
export async function downloadTemplate(): Promise<ImportApiResult<Blob>> {
  try {
    const resp = await apiClient.get<Blob>(
      '/api/canvas/students/import/template.xlsx',
      { responseType: 'blob' },
    );
    const blob = resp.data;
    const url = URL.createObjectURL(blob);
    const a = document.createElement('a');
    a.href = url;
    a.download = 'student_import_template.xlsx';
    document.body.appendChild(a);
    a.click();
    a.remove();
    URL.revokeObjectURL(url);
    return { success: true, data: blob };
  } catch (error: unknown) {
    const e = extractError(error);
    return { success: false, error: e.message, error_code: e.code, http_status: e.status };
  }
}

/**
 * Convenience: build the URL of the template endpoint (for direct <a href>).
 * Note: this won't include the JWT, so prefer downloadTemplate() instead.
 */
export function templateDownloadUrl(): string {
  return '/api/canvas/students/import/template.xlsx';
}

// Re-export for tests / debug
export const _internal = { extractError, getStoredToken };

export const canvasStudentImportApi = {
  previewImport,
  confirmImport,
  getBatch,
  downloadTemplate,
  templateDownloadUrl,
};

export default canvasStudentImportApi;
