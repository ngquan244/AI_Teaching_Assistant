/**
 * Canvas RAG API
 * API calls for Canvas-specific document RAG operations
 * Completely separate from uploaded document RAG
 */

import axios from 'axios';
import { getCanvasToken, getCanvasBaseUrl } from '../utils/canvasStorage';

const API_BASE = '/api/canvas-rag';

/**
 * Get headers with Canvas token for download requests
 */
function getCanvasHeaders(): Record<string, string> {
  const token = getCanvasToken();
  const baseUrl = getCanvasBaseUrl();
  
  const headers: Record<string, string> = {};
  
  if (token) {
    headers['X-Canvas-Token'] = token;
  }
  if (baseUrl) {
    headers['X-Canvas-Base-Url'] = baseUrl;
  }
  
  return headers;
}

// ===== Types =====

export interface CanvasDownloadRequest {
  url: string;
  filename: string;
  course_id: number;
  file_id: number;
}

export interface CanvasDownloadResponse {
  success: boolean;
  status: 'saved' | 'duplicate' | 'failed';
  md5_hash?: string;
  filename?: string;
  file_path?: string;
  existing_filename?: string;
  message?: string;
  error?: string;
}

export interface CanvasIndexRequest {
  filename: string;
}

export interface CanvasIndexResponse {
  success: boolean;
  message?: string;
  file_hash?: string;
  filename?: string;
  pages_loaded?: number;
  chunks_added?: number;
  already_indexed?: boolean;
  topics_extracted?: number;
  topics?: Array<{ name: string; description: string }>;
  error?: string;
}

export interface CanvasExtractTopicsRequest {
  filename: string;
  num_topics?: number;
}

export interface CanvasTopicsResponse {
  success: boolean;
  topics: string[];
  filename: string;
  error?: string;
}

export interface CanvasUpdateTopicsRequest {
  filename: string;
  topics: string[];
}

export interface CanvasFile {
  filename: string;
  size: number;
  modified: number;
  is_indexed: boolean;
}

export interface CanvasIndexedDocument {
  filename: string;
  original_filename: string;
  file_hash: string;
  indexed_at: string;
  chunks_added: number;
  topic_count: number;
}

export interface CanvasStats {
  total_documents: number;
  total_chunks: number;
  collection_name: string;
  unique_files: number;
}

export interface CanvasQueryRequest {
  question: string;
  k?: number;
  return_context?: boolean;
}

export interface CanvasQueryResponse {
  success: boolean;
  answer?: string;
  sources?: Array<{
    content: string;
    source: string;
    page?: number;
    score?: number;
  }>;
  context?: string;
  error?: string;
}

export interface CanvasQuizRequest {
  topics: string[];
  num_questions?: number;
  difficulty?: 'easy' | 'medium' | 'hard';
  language?: 'vi' | 'en';
  k?: number;
  selected_documents?: string[];
}

export interface CanvasQuizQuestion {
  question_number: number;
  question: string;
  options: {
    A: string;
    B: string;
    C: string;
    D: string;
  };
  correct_answer: string;
  explanation?: string;
}

export interface CanvasQuizResponse {
  success: boolean;
  questions: CanvasQuizQuestion[];
  topic?: string;
  error?: string;
}

// ===== API Functions =====

/**
 * Download a file from Canvas with MD5 deduplication
 */
export async function downloadCanvasFile(
  request: CanvasDownloadRequest
): Promise<CanvasDownloadResponse> {
  const response = await axios.post<CanvasDownloadResponse>(
    `${API_BASE}/download`,
    request,
    { headers: getCanvasHeaders() }
  );
  return response.data;
}

/**
 * Index a downloaded Canvas file
 */
export async function indexCanvasFile(
  filename: string
): Promise<CanvasIndexResponse> {
  const response = await axios.post<CanvasIndexResponse>(
    `${API_BASE}/index`,
    { filename }
  );
  return response.data;
}

/**
 * Extract topics from a Canvas file
 */
export async function extractCanvasTopics(
  filename: string,
  numTopics: number = 8
): Promise<CanvasTopicsResponse> {
  const response = await axios.post<CanvasTopicsResponse>(
    `${API_BASE}/extract-topics`,
    { filename, num_topics: numTopics }
  );
  return response.data;
}

/**
 * Get topics for a Canvas document
 */
export async function getCanvasDocumentTopics(
  filename: string
): Promise<CanvasTopicsResponse> {
  const response = await axios.get<CanvasTopicsResponse>(
    `${API_BASE}/topics/${encodeURIComponent(filename)}`
  );
  return response.data;
}

/**
 * Update topics for a Canvas document
 */
export async function updateCanvasDocumentTopics(
  filename: string,
  topics: string[]
): Promise<{ success: boolean; message?: string }> {
  const response = await axios.put(`${API_BASE}/topics`, {
    filename,
    topics,
  });
  return response.data;
}

/**
 * List all downloaded Canvas files
 */
export async function listCanvasFiles(): Promise<{
  success: boolean;
  files: CanvasFile[];
  count: number;
}> {
  const response = await axios.get(`${API_BASE}/files`);
  return response.data;
}

/**
 * List all indexed Canvas documents
 */
export async function listIndexedCanvasDocuments(): Promise<{
  success: boolean;
  documents: CanvasIndexedDocument[];
  count: number;
}> {
  const response = await axios.get(`${API_BASE}/indexed`);
  return response.data;
}

/**
 * Get Canvas index statistics
 */
export async function getCanvasStats(): Promise<{
  success: boolean;
  stats: CanvasStats;
}> {
  const response = await axios.get(`${API_BASE}/stats`);
  return response.data;
}

/**
 * Query Canvas documents
 */
export async function queryCanvasDocuments(
  request: CanvasQueryRequest
): Promise<CanvasQueryResponse> {
  const response = await axios.post<CanvasQueryResponse>(
    `${API_BASE}/query`,
    request
  );
  return response.data;
}

/**
 * Generate quiz from Canvas documents
 */
export async function generateCanvasQuiz(
  request: CanvasQuizRequest
): Promise<CanvasQuizResponse> {
  const response = await axios.post<CanvasQuizResponse>(
    `${API_BASE}/generate-quiz`,
    request
  );
  return response.data;
}

/**
 * Reset Canvas index
 */
export async function resetCanvasIndex(): Promise<{
  success: boolean;
  message?: string;
}> {
  const response = await axios.post(`${API_BASE}/reset`);
  return response.data;
}

/**
 * Delete a Canvas file
 */
export async function deleteCanvasFile(
  filename: string
): Promise<{ success: boolean; message?: string }> {
  const response = await axios.delete(
    `${API_BASE}/files/${encodeURIComponent(filename)}`
  );
  return response.data;
}

/**
 * Remove index for a Canvas file (keep the file)
 */
export async function removeCanvasFileIndex(
  filename: string
): Promise<{ success: boolean; message?: string }> {
  const response = await axios.delete(
    `${API_BASE}/index/${encodeURIComponent(filename)}`
  );
  return response.data;
}

export const canvasRagApi = {
  downloadCanvasFile,
  indexCanvasFile,
  extractCanvasTopics,
  getCanvasDocumentTopics,
  updateCanvasDocumentTopics,
  listCanvasFiles,
  listIndexedCanvasDocuments,
  getCanvasStats,
  queryCanvasDocuments,
  generateCanvasQuiz,
  resetCanvasIndex,
  deleteCanvasFile,
  removeCanvasFileIndex,
};

export default canvasRagApi;
