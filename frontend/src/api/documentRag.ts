import { apiClient } from './client';

// ===== Types =====

export interface RAGSource {
  source: string;
  page: number;
  filename: string;
  snippet: string;
}

export interface RAGQueryRequest {
  question: string;
  k?: number;
  return_context?: boolean;
}

export interface RAGQueryResponse {
  success: boolean;
  answer: string;
  sources: RAGSource[];
  context?: string;
  error?: string;
}

export interface RAGIngestResponse {
  success: boolean;
  message: string;
  filename?: string;
  file_hash?: string;
  pages_loaded?: number;
  chunks_added?: number;
  already_indexed?: boolean;
  error?: string;
}

export interface RAGIndexStats {
  persist_directory: string;
  collection_name: string;
  embedding_model: string;
  device: string;
  indexed_file_hashes: number;
  total_documents: number;
}

export interface RAGStatsResponse {
  success: boolean;
  stats: RAGIndexStats;
}

export interface RAGUploadedFile {
  filename: string;
  size: number;
  modified: number;
}

export interface RAGFilesResponse {
  success: boolean;
  files: RAGUploadedFile[];
  total: number;
  page: number;
  page_size: number;
  pages: number;
}

export interface LLMStatus {
  connected: boolean;
  model?: string;
  base_url?: string;
  message: string;
  error?: string;
  provider?: string;
  error_type?: string;
}

export interface RAGConfig {
  persist_directory: string;
  collection_name: string;
  llm_provider: string;
  llm_model: string;
  available_providers: string[];

  groq_model: string;
  groq_configured: boolean;
  chunk_size: number;
  chunk_overlap: number;
  embedding_model: string;
  retriever_k: number;
  search_type: string;
}

// LLM Provider Types
export interface LLMProviderInfo {
  success: boolean;
  current_provider: string;
  current_model: string;
  available_providers: string[];
  groq_configured: boolean;
}

export interface SetLLMProviderRequest {
  provider: 'groq';
  model?: string;
}

export interface SetLLMProviderResponse {
  success: boolean;
  provider?: string;
  model?: string;
  message?: string;
  error?: string;
  connection?: LLMStatus;
}

// Quiz Generation Types
export interface QuizQuestion {
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

export interface GenerateQuizRequest {
  topic?: string;  // Single topic (legacy)
  topics?: string[];  // Multiple topics (new)
  num_questions: number;
  difficulty?: 'easy' | 'medium' | 'hard';
  language?: 'vi' | 'en';
  selected_documents?: string[];  // Selected document filenames
}

export interface GenerateQuizResponse {
  success: boolean;
  partial?: boolean;
  questions: QuizQuestion[];
  topic: string;
  num_questions_requested: number;
  num_questions_generated: number;
  context_used?: string;
  raw_response?: string;
  message?: string;
  error?: string;
}

// Topic suggestion types
export interface TopicSuggestion {
  name: string;
  description: string;
  relevance_score?: number;  // Optional score for ordering
}

// Topic with document info (for multi-select)
export interface TopicWithDocument {
  topic: TopicSuggestion;
  documentFilename: string;
  documentOriginalName: string;
}

export interface ExtractTopicsResponse {
  success: boolean;
  topics: TopicSuggestion[];
  message?: string;
}

// ===== API Functions =====

/**
 * Upload a PDF file for RAG
 */
export const uploadRAGDocument = async (file: File): Promise<RAGIngestResponse> => {
  const formData = new FormData();
  formData.append('file', file);

  const response = await apiClient.post<RAGIngestResponse>(
    '/api/document-rag/upload',
    formData,
    {
      headers: {
        'Content-Type': 'multipart/form-data',
      },
    }
  );
  return response.data;
};

/**
 * Build index for an uploaded document
 */
export const buildRAGIndex = async (filename: string): Promise<RAGIngestResponse> => {
  const formData = new FormData();
  formData.append('filename', filename);

  const response = await apiClient.post<RAGIngestResponse>(
    '/api/document-rag/build-index',
    formData
  );
  return response.data;
};

/**
 * Upload and immediately index a PDF document
 */
export const uploadAndIndexDocument = async (file: File): Promise<RAGIngestResponse> => {
  const formData = new FormData();
  formData.append('file', file);

  const response = await apiClient.post<RAGIngestResponse>(
    '/api/document-rag/upload-and-index',
    formData,
    {
      headers: {
        'Content-Type': 'multipart/form-data',
      },
    }
  );
  return response.data;
};

/**
 * Download a file from URL and index it (for Canvas integration)
 */
export interface DownloadAndIndexRequest {
  url: string;
  filename: string;
}

export const downloadAndIndexFromUrl = async (
  request: DownloadAndIndexRequest
): Promise<RAGIngestResponse> => {
  const response = await apiClient.post<RAGIngestResponse>(
    '/api/document-rag/download-and-index',
    request,
    {
      timeout: 120000, // 2 minutes for download + processing
    }
  );
  return response.data;;
};

/**
 * Get index statistics
 */
export const getRAGStats = async (): Promise<RAGStatsResponse> => {
  const response = await apiClient.get<RAGStatsResponse>('/api/document-rag/stats');
  return response.data;
};

/**
 * Reset the document index
 */
export const resetRAGIndex = async (): Promise<{ success: boolean; message?: string; error?: string }> => {
  const response = await apiClient.post('/api/document-rag/reset');
  return response.data;
};

/**
 * Check LLM connection status
 */
export const checkLLMStatus = async (): Promise<LLMStatus> => {
  const response = await apiClient.get<LLMStatus>('/api/document-rag/llm-status');
  return response.data;
};

/**
 * Get RAG configuration
 */
export const getRAGConfig = async (): Promise<{ success: boolean; config: RAGConfig }> => {
  const response = await apiClient.get('/api/document-rag/config');
  return response.data;
};

/**
 * List uploaded files (paginated)
 */
export const listUploadedFiles = async (page = 1, pageSize = 10): Promise<RAGFilesResponse> => {
  const response = await apiClient.get<RAGFilesResponse>('/api/document-rag/uploaded-files', {
    params: { page, page_size: pageSize },
  });
  return response.data;
};

/**
 * Delete an uploaded file
 */
export const deleteUploadedFile = async (filename: string): Promise<{ success: boolean; message: string }> => {
  const response = await apiClient.delete(`/api/document-rag/uploaded-files/${encodeURIComponent(filename)}`);
  return response.data;
};

/**
 * Generate quiz from indexed documents
 */
export const generateQuiz = async (request: GenerateQuizRequest): Promise<GenerateQuizResponse> => {
  const response = await apiClient.post<GenerateQuizResponse>(
    '/api/document-rag/generate-quiz',
    request
  );
  return response.data;
};

/**
 * Export quiz to QTI format
 */
export const exportQuizToQTI = async (
  questions: QuizQuestion[],
  title: string = "Generated Quiz",
  description: string = ""
): Promise<Blob> => {
  const response = await apiClient.post(
    '/api/document-rag/export-quiz-qti',
    { questions, title, description },
    { responseType: 'blob' }
  );
  return response.data;
};

/**
 * Extract suggested topics from indexed documents
 */
export const extractTopics = async (): Promise<ExtractTopicsResponse> => {
  const response = await apiClient.get<ExtractTopicsResponse>('/api/document-rag/extract-topics');
  return response.data;
};

/**
 * Get cached topics for a specific indexed document
 * Topics are extracted during indexing, so this is instant (no LLM call)
 */
export const getDocumentTopics = async (filename: string): Promise<{
  success: boolean;
  filename: string;
  topics: string[];
  count: number;
}> => {
  const response = await apiClient.get(`/api/document-rag/document-topics/${encodeURIComponent(filename)}`);
  return response.data;
};

/**
 * Update topics for a specific document
 */
export const updateDocumentTopics = async (filename: string, topics: string[]): Promise<{
  success: boolean;
  filename: string;
  topics: string[];
  count: number;
  message: string;
}> => {
  const response = await apiClient.put(`/api/document-rag/document-topics/${encodeURIComponent(filename)}`, {
    topics
  });
  return response.data;
};

/**
 * Get topics for multiple documents at once
 */
export const getMultipleDocumentTopics = async (filenames: string[]): Promise<{
  success: boolean;
  documents: Array<{
    filename: string;
    topics: string[];
  }>;
}> => {
  const results = await Promise.all(
    filenames.map(filename => getDocumentTopics(filename))
  );
  
  return {
    success: true,
    documents: results.map((result, idx) => ({
      filename: filenames[idx],
      topics: result.success ? result.topics : []
    }))
  };
};

/**
 * List all indexed documents with their topic counts (paginated)
 */
export const listIndexedDocuments = async (page = 1, pageSize = 10): Promise<{
  success: boolean;
  documents: Array<{
    filename: string;
    original_filename: string;
    topic_count: number;
    indexed_at: string;
  }>;
  total: number;
  page: number;
  page_size: number;
  pages: number;
}> => {
  const response = await apiClient.get('/api/document-rag/indexed-documents', {
    params: { page, page_size: pageSize },
  });
  return response.data;
};

// ===== LLM Provider API Functions =====

/**
 * Get current LLM provider information
 */
export const getLLMProviderInfo = async (): Promise<LLMProviderInfo> => {
  const response = await apiClient.get<LLMProviderInfo>('/api/document-rag/llm-provider');
  return response.data;
};

/**
 * Set/switch LLM provider at runtime
 */
export const setLLMProvider = async (request: SetLLMProviderRequest): Promise<SetLLMProviderResponse> => {
  const response = await apiClient.post<SetLLMProviderResponse>(
    '/api/document-rag/set-llm',
    request
  );
  return response.data;
};



// ===== Async (Celery) API Functions =====

import type { AsyncJobResponse } from './jobs';

/**
 * Upload and index a document asynchronously via Celery.
 * Returns immediately with a job_id — poll /api/jobs/{job_id} for result.
 */
export const asyncUploadAndIndex = async (file: File): Promise<AsyncJobResponse> => {
  const formData = new FormData();
  formData.append('file', file);

  const response = await apiClient.post<AsyncJobResponse>(
    '/api/document-rag/async/upload-and-index',
    formData,
    { headers: { 'Content-Type': 'multipart/form-data' } },
  );
  return response.data;
};

/**
 * Generate quiz asynchronously via Celery.
 */
export const asyncGenerateQuiz = async (request: GenerateQuizRequest): Promise<AsyncJobResponse> => {
  const response = await apiClient.post<AsyncJobResponse>(
    '/api/document-rag/async/generate-quiz',
    request,
  );
  return response.data;
};

/**
 * Build index asynchronously via Celery.
 */
export const asyncBuildIndex = async (filename: string): Promise<AsyncJobResponse> => {
  const formData = new FormData();
  formData.append('filename', filename);

  const response = await apiClient.post<AsyncJobResponse>(
    '/api/document-rag/async/build-index',
    formData,
  );
  return response.data;
};

/**
 * Extract topics asynchronously via Celery.
 */
export const asyncExtractTopics = async (): Promise<AsyncJobResponse> => {
  const response = await apiClient.post<AsyncJobResponse>(
    '/api/document-rag/async/extract-topics',
  );
  return response.data;
};
