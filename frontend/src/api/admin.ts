/**
 * Admin API client
 * Handles admin-only endpoints: dashboard, user management, job monitoring
 */
import { apiClient } from './client';

// =============================================================================
// Types
// =============================================================================

export interface DashboardStats {
  users: {
    total: number;
    active: number;
    disabled: number;
    pending: number;
    new_24h: number;
    new_7d: number;
  };
  jobs: {
    total: number;
    succeeded: number;
    failed: number;
    running: number;
    last_24h: number;
    success_rate: number;
    type_distribution: Record<string, number>;
  };
  canvas_tokens: {
    total: number;
    active: number;
  };
}

export interface AdminUser {
  id: string;
  email: string;
  name: string;
  role: 'ADMIN' | 'TEACHER';
  status: 'ACTIVE' | 'DISABLED' | 'PENDING';
  created_at: string;
  updated_at: string | null;
  last_login_at: string | null;
}

export interface AdminUserList {
  items: AdminUser[];
  total: number;
  page: number;
  page_size: number;
  pages: number;
}

export interface AdminJob {
  id: string;
  user_id: string | null;
  user_email: string | null;
  user_name: string | null;
  job_type: string;
  status: string;
  progress_pct: number;
  current_step: string | null;
  error_message: string | null;
  created_at: string | null;
  started_at: string | null;
  finished_at: string | null;
}

export interface AdminJobList {
  items: AdminJob[];
  total: number;
  page: number;
  page_size: number;
  pages: number;
}

export interface UpdateUserRequest {
  name?: string;
  role?: 'ADMIN' | 'TEACHER';
  status?: 'ACTIVE' | 'DISABLED' | 'PENDING';
}

export interface ResetPasswordRequest {
  new_password: string;
}

export interface MessageResponse {
  success: boolean;
  message: string;
}

// Panel visibility config
export interface PanelConfig {
  panels: Record<string, boolean>;
  labels: Record<string, string>;
  all_panels: string[];
}

export interface UpdatePanelConfigRequest {
  panels: Record<string, boolean>;
}

// =============================================================================
// API Functions
// =============================================================================

/** Get dashboard statistics */
export async function getDashboardStats(): Promise<DashboardStats> {
  const response = await apiClient.get<DashboardStats>('/api/admin/dashboard');
  return response.data;
}

/** List users with filtering */
export async function listUsers(params?: {
  page?: number;
  page_size?: number;
  role?: string;
  status?: string;
  search?: string;
}): Promise<AdminUserList> {
  const response = await apiClient.get<AdminUserList>('/api/admin/users', { params });
  return response.data;
}

/** Get a single user */
export async function getUser(userId: string): Promise<AdminUser> {
  const response = await apiClient.get<AdminUser>(`/api/admin/users/${userId}`);
  return response.data;
}

/** Update a user */
export async function updateUser(userId: string, data: UpdateUserRequest): Promise<AdminUser> {
  const response = await apiClient.patch<AdminUser>(`/api/admin/users/${userId}`, data);
  return response.data;
}

/** Reset user password */
export async function resetUserPassword(userId: string, data: ResetPasswordRequest): Promise<MessageResponse> {
  const response = await apiClient.post<MessageResponse>(`/api/admin/users/${userId}/reset-password`, data);
  return response.data;
}

/** Delete a user */
export async function deleteUser(userId: string): Promise<MessageResponse> {
  const response = await apiClient.delete<MessageResponse>(`/api/admin/users/${userId}`);
  return response.data;
}

/** List all jobs (admin) */
export async function listAllJobs(params?: {
  page?: number;
  page_size?: number;
  user_id?: string;
  job_type?: string;
  status?: string;
}): Promise<AdminJobList> {
  const response = await apiClient.get<AdminJobList>('/api/admin/jobs', { params });
  return response.data;
}

// =============================================================================
// Panel Config
// =============================================================================

/** Get panel visibility config (public — any authenticated user) */
export async function getPanelConfig(): Promise<PanelConfig> {
  const response = await apiClient.get<PanelConfig>('/api/config/panels');
  return response.data;
}

/** Get panel visibility config (admin endpoint — includes all_panels) */
export async function getAdminPanelConfig(): Promise<PanelConfig> {
  const response = await apiClient.get<PanelConfig>('/api/admin/panels');
  return response.data;
}

/** Update panel visibility (admin only) */
export async function updatePanelConfig(data: UpdatePanelConfigRequest): Promise<PanelConfig> {
  const response = await apiClient.put<PanelConfig>('/api/admin/panels', data);
  return response.data;
}

export const adminApi = {
  getDashboardStats,
  listUsers,
  getUser,
  updateUser,
  resetUserPassword,
  deleteUser,
  listAllJobs,
  getPanelConfig,
  getAdminPanelConfig,
  updatePanelConfig,
};
