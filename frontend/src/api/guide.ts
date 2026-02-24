/**
 * Guide API client
 * Fetches and updates the user guide (markdown).
 */
import { apiClient } from './client';

export interface GuideResponse {
  content: string;
  success: boolean;
}

/** Get user guide content (any authenticated user) */
export async function getGuide(): Promise<GuideResponse> {
  const response = await apiClient.get<GuideResponse>('/api/guide');
  return response.data;
}

/** Update user guide content (admin only) */
export async function updateGuide(content: string): Promise<GuideResponse> {
  const response = await apiClient.put<GuideResponse>('/api/guide', { content });
  return response.data;
}
