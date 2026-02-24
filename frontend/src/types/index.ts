// ============================================================================
// Teaching Assistant Grader - TypeScript Types
// ============================================================================

// ===== Common Types =====
export type MessageRole = 'user' | 'assistant';

// ===== Chat Types =====
export interface ChatMessage {
  role: MessageRole;
  content: string;
}

export interface ToolUsage {
  tool: string;
  args: Record<string, unknown>;
}

export interface ChatRequest {
  message: string;
  history: ChatMessage[];
  model: string;
  max_iterations: number;
}

export interface ChatResponse {
  response: string;
  iterations: number;
  tools_used: ToolUsage[];
  success: boolean;
  error?: string;
}

export interface UploadResponse {
  success: boolean;
  message: string;
  files: string[];
  count: number;
}

export interface QuizQuestion {
  question: string;
  options: Record<string, string>;
  correct: Record<string, string>;
}

export interface QuizGenerateRequest {
  num_questions: number;
  source_pdf?: string;
}

export interface QuizGenerateResponse {
  success: boolean;
  quiz_id: string;
  num_questions: number;
  html_file: string;
  file_url: string;
  message: string;
}

export interface QuizListItem {
  id: string;
  timestamp: string;
  num_questions: number;
  source_pdf?: string;
}

export interface GradingRequest {
  exam_code?: string;
}

export interface GradingResult {
  student_id: string;
  full_name: string;
  email: string;
  exam_code: string;
  score: number;
  evaluation: string;
}

export interface GradingSummary {
  total_students: number;
  average_score: number;
  max_score: number;
  min_score: number;
}

export interface GradingResponse {
  success: boolean;
  exam_code: string;
  summary?: GradingSummary;
  overall_assessment?: string;
  results: GradingResult[];
  excel_file?: string;
  error?: string;
}

export interface ConfigResponse {
  available_models: string[];
  default_model: string;
  max_iterations: number;
  llm_provider: string;
  groq_available: boolean;
}

// ===== API Response Types =====
export interface ApiResponse<T = unknown> {
  success: boolean;
  data?: T;
  error?: string;
  message?: string;
}

// ===== Constants =====
export const TABS = {
  CHAT: 'chat',
  UPLOAD: 'upload',
  QUIZ: 'quiz',
  GRADING: 'grading',
  DOCUMENT_RAG: 'document_rag',
  CANVAS: 'canvas',
  CANVAS_QUIZ: 'canvas_quiz',
  GUIDE: 'guide',
  SETTINGS: 'settings',
} as const;

export type TabType = typeof TABS[keyof typeof TABS];

/** Map each tab → URL path segment (no leading slash) */
export const TAB_PATHS: Record<TabType, string> = {
  [TABS.CHAT]: 'chat',
  [TABS.UPLOAD]: 'upload',
  [TABS.QUIZ]: 'quiz',
  [TABS.GRADING]: 'grading',
  [TABS.DOCUMENT_RAG]: 'rag',
  [TABS.CANVAS]: 'canvas',
  [TABS.CANVAS_QUIZ]: 'quiz-builder',
  [TABS.GUIDE]: 'guide',
  [TABS.SETTINGS]: 'settings',
};

/** Reverse lookup: URL path segment → TabType. Falls back to CHAT. */
export function pathToTab(path: string): TabType {
  // strip leading slash(es)
  const segment = path.replace(/^\/+/, '').split('/')[0] || '';
  const entry = Object.entries(TAB_PATHS).find(([, p]) => p === segment);
  return (entry ? entry[0] : TABS.CHAT) as TabType;
}

// Re-export Canvas types
export * from './canvas';
