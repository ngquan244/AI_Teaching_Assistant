// ============================================================================
// Canvas LMS Integration Types
// ============================================================================

export interface CanvasCourse {
  id: number;
  name: string;
  course_code: string;
  enrollment_term_id?: number;
  start_at?: string;
  end_at?: string;
  workflow_state?: string;
}

export interface CanvasFile {
  id: number;
  uuid: string;
  folder_id: number;
  display_name: string;
  filename: string;
  content_type: string;
  url: string; // Signed download URL
  size: number;
  created_at: string;
  updated_at: string;
  modified_at: string;
  locked: boolean;
  hidden: boolean;
}

// Download status for UI
export type FileDownloadStatus = 
  | 'queued'
  | 'downloading'
  | 'hashing'
  | 'saved'
  | 'duplicate'
  | 'failed';

export interface FileDownloadState {
  fileId: number;
  filename: string;
  status: FileDownloadStatus;
  progress?: number;
  error?: string;
  md5Hash?: string;
}

// API Request/Response types
export interface CanvasCoursesResponse {
  success: boolean;
  courses: CanvasCourse[];
  error?: string;
}

export interface CanvasFilesResponse {
  success: boolean;
  files: CanvasFile[];
  course_id: number;
  error?: string;
}

export interface FileDownloadRequest {
  file_id: number;
  filename: string;
  url: string;
  course_id: number;
}

export interface FileDownloadResponse {
  success: boolean;
  file_id: number;
  filename: string;
  status: FileDownloadStatus;
  md5_hash?: string;
  saved_path?: string;
  error?: string;
}

export interface BatchDownloadRequest {
  course_id: number;
  files: FileDownloadRequest[];
}

export interface BatchDownloadResponse {
  success: boolean;
  results: FileDownloadResponse[];
  total: number;
  saved: number;
  duplicates: number;
  failed: number;
}

// Canvas settings stored in localStorage
export interface CanvasSettings {
  accessToken: string;
  baseUrl: string; // e.g., https://lms.uet.vnu.edu.vn
  selectedCourseId?: number;
  selectedCourseName?: string;
}

// ============================================================================
// Canvas QTI Import Types (Content Migration)
// ============================================================================

export type ImportProgressStatus = 
  | 'idle'
  | 'creating_migration'
  | 'uploading_to_s3'
  | 'processing'
  | 'completed'
  | 'failed';

export interface QTIImportRequest {
  course_id: number;
  question_bank_name: string;
  qti_zip_base64: string;  // Base64 encoded zip file
  filename?: string;
}

export interface QTIImportResponse {
  success: boolean;
  status: ImportProgressStatus;
  migration_id?: number;
  question_bank_name?: string;
  message?: string;
  error?: string;
  progress_url?: string;
}

export interface ImportProgress {
  status: ImportProgressStatus;
  message: string;
  progress?: number;  // 0-100
  error?: string;
}
