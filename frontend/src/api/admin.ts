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

// Model/provider visibility config
export interface ModelConfig {
  providers: Record<string, boolean>;
  models: Record<string, Record<string, boolean>>;
  all_providers: string[];
  all_models: Record<string, string[]>;
  provider_labels: Record<string, string>;
  provider_descriptions: Record<string, string>;
  model_labels: Record<string, string>;
}

export interface UpdateModelConfigRequest {
  providers?: Record<string, boolean>;
  models?: Record<string, Record<string, boolean>>;
}

// Public model config (for teacher UI filtering)
export interface ModelsConfigPublic {
  enabled_providers: string[];
  enabled_models: Record<string, string[]>;
  provider_labels: Record<string, string>;
  model_labels: Record<string, string>;
}

// =============================================================================
// Tool Config Types
// =============================================================================

export interface ToolConfig {
  tools: Record<string, boolean>;
  all_tools: string[];
  tool_labels: Record<string, string>;
  tool_descriptions: Record<string, string>;
}

export interface UpdateToolConfigRequest {
  tools: Record<string, boolean>;
}

export interface ToolsConfigPublic {
  enabled_tools: string[];
  tool_labels: Record<string, string>;
  tool_descriptions: Record<string, string>;
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

// =============================================================================
// Model Config
// =============================================================================

/** Get model/provider config (public — any authenticated user) */
export async function getModelsConfig(): Promise<ModelsConfigPublic> {
  const response = await apiClient.get<ModelsConfigPublic>('/api/config/models-config');
  return response.data;
}

/** Get model/provider config (admin — full detail) */
export async function getAdminModelConfig(): Promise<ModelConfig> {
  const response = await apiClient.get<ModelConfig>('/api/admin/models');
  return response.data;
}

/** Update model/provider config (admin only) */
export async function updateModelConfig(data: UpdateModelConfigRequest): Promise<ModelConfig> {
  const response = await apiClient.put<ModelConfig>('/api/admin/models', data);
  return response.data;
}

// =============================================================================
// Tool Config
// =============================================================================

/** Get tool config (public — any authenticated user) */
export async function getToolsConfig(): Promise<ToolsConfigPublic> {
  const response = await apiClient.get<ToolsConfigPublic>('/api/config/tools-config');
  return response.data;
}

/** Get tool config (admin — full detail) */
export async function getAdminToolConfig(): Promise<ToolConfig> {
  const response = await apiClient.get<ToolConfig>('/api/admin/tools');
  return response.data;
}

/** Update tool config (admin only) */
export async function updateToolConfig(data: UpdateToolConfigRequest): Promise<ToolConfig> {
  const response = await apiClient.put<ToolConfig>('/api/admin/tools', data);
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
  getModelsConfig,
  getAdminModelConfig,
  updateModelConfig,
  getToolsConfig,
  getAdminToolConfig,
  updateToolConfig,
};
