/**
 * Guide API client
 * CRUD operations for per-panel guide documents.
 */
import { apiClient } from './client';

// ─── Types ───────────────────────────────────────────────────────────

export interface GuideListItem {
  panel_key: string;
  title: string;
  description: string | null;
  icon_name: string | null;
  sort_order: number;
  is_published: boolean;
}

export interface GuideListResponse {
  guides: GuideListItem[];
  success: boolean;
}

export interface GuideDetailResponse {
  panel_key: string;
  title: string;
  description: string | null;
  icon_name: string | null;
  content: string;
  sort_order: number;
  is_published: boolean;
  success: boolean;
}

export interface GuideUpdateRequest {
  title?: string;
  description?: string;
  icon_name?: string;
  content?: string;
  sort_order?: number;
  is_published?: boolean;
}

export interface GuideCreateRequest {
  panel_key: string;
  title: string;
  content?: string;
  description?: string;
  icon_name?: string;
  sort_order?: number;
  is_published?: boolean;
}

export interface ImageUploadResponse {
  url: string;
  filename: string;
  success: boolean;
}

// ─── API calls ───────────────────────────────────────────────────────

/** List all guide documents (filtered by panel visibility for non-admin) */
export async function getGuideList(): Promise<GuideListResponse> {
  const response = await apiClient.get<GuideListResponse>('/api/guide');
  return response.data;
}

/** Get full content of a guide document by panel_key */
export async function getGuideByPanel(panelKey: string): Promise<GuideDetailResponse> {
  const response = await apiClient.get<GuideDetailResponse>(`/api/guide/${panelKey}`);
  return response.data;
}

/** Update a guide document (admin only) */
export async function updateGuide(panelKey: string, data: GuideUpdateRequest): Promise<GuideDetailResponse> {
  const response = await apiClient.put<GuideDetailResponse>(`/api/guide/${panelKey}`, data);
  return response.data;
}

/** Create a new guide document (admin only) */
export async function createGuide(data: GuideCreateRequest): Promise<GuideDetailResponse> {
  const response = await apiClient.post<GuideDetailResponse>('/api/guide', data);
  return response.data;
}

/** Delete a guide document (admin only) */
export async function deleteGuide(panelKey: string): Promise<{ success: boolean; message: string }> {
  const response = await apiClient.delete(`/api/guide/${panelKey}`);
  return response.data;
}

/** Upload an image for use in guide markdown (admin only) */
export async function uploadGuideImage(file: File): Promise<ImageUploadResponse> {
  const formData = new FormData();
  formData.append('file', file);
  const response = await apiClient.post<ImageUploadResponse>('/api/guide/images', formData, {
    headers: { 'Content-Type': 'multipart/form-data' },
  });
  return response.data;
}
