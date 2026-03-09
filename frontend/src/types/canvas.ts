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


// ============================================================================
// Canvas Quiz Builder Types
// ============================================================================

/** A question displayed in the Quiz Builder UI (internal app format). */
export interface QuizBuilderQuestion {
  /** Original question text */
  question: string;
  /** Answer options keyed by letter: { "A": "...", "B": "..." } */
  options: Record<string, string>;
  /** Correct option(s) keyed by letter: { "A": "correct text" } */
  correct: Record<string, string>;
}

export interface CanvasQuiz {
  id: number;
  title: string;
  html_url?: string;
  description?: string;
  quiz_type?: string;
  time_limit?: number | null;
  shuffle_answers?: boolean;
  allowed_attempts?: number;
  question_count?: number;
  points_possible?: number;
  published?: boolean;
}

export interface CanvasQuizCreate {
  title: string;
  description?: string;
  quiz_type: 'assignment' | 'practice_quiz' | 'graded_survey' | 'survey';
  time_limit?: number | null;
  shuffle_answers: boolean;
  allowed_attempts: number;
  published: boolean;
}

/** A question provided directly by the client (sent to backend). */
export interface DirectQuizQuestion {
  question_text: string;
  question_type?: string;
  options: Record<string, string>;
  correct_keys: string[];
  points?: number;
}

/** Copy questions from an existing Canvas quiz. */
export interface SourceQuizSelect {
  source_quiz_id: number;
  question_ids: number[];
}

export interface CreateCanvasQuizRequest {
  course_id: number;
  quiz: CanvasQuizCreate;
  direct_questions: DirectQuizQuestion[];
  source_questions: SourceQuizSelect[];
  default_points: number;
  bank_questions?: BankQuestionSelect[];
  question_groups?: QuestionGroupConfig[];
}

export interface CreateCanvasQuizResponse {
  success: boolean;
  quiz_id?: number;
  quiz_url?: string;
  title?: string;
  questions_added?: number;
  groups_created?: number;
  message?: string;
  error?: string;
}

// ============================================================================
// Canvas Assessment Question Bank Types
// ============================================================================

export interface AssessmentQuestionBank {
  id: number;
  title: string;
  assessment_question_count?: number;
}

export interface AssessmentQuestion {
  id: number;
  question_name?: string;
  question_text?: string;
  question_type?: string;
  points_possible?: number;
}

export interface BankQuestionSelect {
  bank_id: number;
  question_ids: number[];
}

export interface QuestionGroupConfig {
  bank_id: number;
  name: string;
  pick_count: number;
  question_points: number;
}

export interface ImportProgress {
  status: ImportProgressStatus;
  message: string;
  progress?: number;  // 0-100
  error?: string;
}
