// ============================================================================
// Teaching Assistant Grader - TypeScript Types
// ============================================================================

// ===== Common Types =====
export type MessageRole = 'user' | 'assistant';

export interface ConfigResponse {
  default_model: string;
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
  DOCUMENT_RAG: 'document_rag',
  CANVAS: 'canvas',
  CANVAS_QUIZ: 'canvas_quiz',
  SAVED_QUIZZES: 'saved_quizzes',
  CANVAS_SIMULATION: 'canvas_simulation',
  CANVAS_RESULTS: 'canvas_results',
  GUIDE: 'guide',
  SETTINGS: 'settings',
} as const;

export type TabType = typeof TABS[keyof typeof TABS];

/** Map each tab → URL path segment (no leading slash) */
export const TAB_PATHS: Record<TabType, string> = {
  [TABS.DOCUMENT_RAG]: 'rag',
  [TABS.CANVAS]: 'canvas',
  [TABS.CANVAS_QUIZ]: 'quiz-builder',
  [TABS.SAVED_QUIZZES]: 'saved-quizzes',
  [TABS.CANVAS_SIMULATION]: 'canvas-sim',
  [TABS.CANVAS_RESULTS]: 'canvas-results',
  [TABS.GUIDE]: 'guide',
  [TABS.SETTINGS]: 'settings',
};

/** Reverse lookup: URL path segment → TabType. Falls back to GUIDE. */
export function pathToTab(path: string): TabType {
  // strip leading slash(es)
  const segment = path.replace(/^\/+/, '').split('/')[0] || '';
  const entry = Object.entries(TAB_PATHS).find(([, p]) => p === segment);
  return (entry ? entry[0] : TABS.GUIDE) as TabType;
}

/** Extract guide section from URL path (e.g. /guide/chat → 'chat') */
export function getGuideSectionFromPath(path: string): string | null {
  const match = path.match(/^\/guide\/(.+)$/);
  return match ? match[1] : null;
}


// Re-export Canvas types
export * from './canvas';
