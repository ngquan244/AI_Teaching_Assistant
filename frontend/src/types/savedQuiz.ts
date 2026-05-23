// ============================================================================
// Saved Quiz Types
// ============================================================================

export interface SavedQuizQuestion {
  id: string;
  question_number: number;
  question_text: string;
  options: Record<string, string>;
  correct_answer: string;
  explanation: string | null;
  question_type: string;
  points: number;
}

export interface SavedQuiz {
  id: string;
  title: string;
  course_id: number | null;
  course_name: string | null;
  description: string | null;
  difficulty: string | null;
  language: string | null;
  source: string;
  tags: string[];
  question_count: number;
  is_starred: boolean;
  created_at: string;
  updated_at: string | null;
}

export interface SavedQuizDetail extends SavedQuiz {
  questions: SavedQuizQuestion[];
}

export interface CourseGroup {
  course_id: number | null;
  course_name: string | null;
  quiz_count: number;
}

export interface SavedQuizListResponse {
  items: SavedQuiz[];
  total: number;
  page: number;
  page_size: number;
  courses: CourseGroup[];
}

export interface SavedQuizCreateRequest {
  title: string;
  course_id?: number | null;
  course_name?: string | null;
  description?: string | null;
  difficulty?: string | null;
  language?: string | null;
  source?: string;
  source_job_id?: string | null;
  tags?: string[];
  questions: SavedQuizQuestionCreate[];
}

export interface SavedQuizQuestionCreate {
  question_text: string;
  options: Record<string, string>;
  correct_answer: string;
  explanation?: string | null;
  question_type?: string;
  points?: number;
}

export interface SavedQuizUpdateRequest {
  title?: string;
  description?: string | null;
  difficulty?: string | null;
  language?: string | null;
  course_id?: number | null;
  course_name?: string | null;
  tags?: string[];
  is_starred?: boolean;
}
