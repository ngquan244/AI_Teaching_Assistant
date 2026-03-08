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

// =============================================================================
// Invite Code Types
// =============================================================================

export interface InviteCode {
  id: string;
  code_prefix: string;
  label: string | null;
  max_uses: number | null;
  used_count: number;
  is_active: boolean;
  is_usable: boolean;
  expires_at: string | null;
  created_by_email: string | null;
  created_at: string;
  updated_at: string;
}

export interface InviteCodeCreated extends InviteCode {
  plaintext_code: string;
}

export interface InviteCodeList {
  items: InviteCode[];
  total: number;
  page: number;
  page_size: number;
  pages: number;
}

export interface CreateInviteCodeRequest {
  label?: string;
  max_uses?: number;
  expires_at?: string;
}

export interface UpdateInviteCodeRequest {
  label?: string;
  max_uses?: number;
  is_active?: boolean;
  expires_at?: string;
}

export interface InviteCodeUsage {
  id: string;
  user_email: string | null;
  user_name: string | null;
  used_at: string;
}

export interface InviteCodeUsageList {
  items: InviteCodeUsage[];
  total: number;
  page: number;
  page_size: number;
  pages: number;
}

export interface InviteCodeStats {
  total_codes: number;
  active_codes: number;
  total_usages: number;
}

export interface SignupSettings {
  mode: 'open' | 'invite' | 'closed';
}

// =============================================================================
// Invite Code API Functions
// =============================================================================

/** Get current signup settings */
export async function getSignupSettings(): Promise<SignupSettings> {
  const response = await apiClient.get<SignupSettings>('/api/admin/signup-settings');
  return response.data;
}

/** Update signup settings */
export async function updateSignupSettings(data: { mode: string }): Promise<SignupSettings> {
  const response = await apiClient.put<SignupSettings>('/api/admin/signup-settings', data);
  return response.data;
}

/** Get invite code stats */
export async function getInviteCodeStats(): Promise<InviteCodeStats> {
  const response = await apiClient.get<InviteCodeStats>('/api/admin/invite-codes/stats');
  return response.data;
}

/** List invite codes with pagination */
export async function listInviteCodes(
  page = 1,
  pageSize = 20,
  activeOnly = false,
): Promise<InviteCodeList> {
  const response = await apiClient.get<InviteCodeList>('/api/admin/invite-codes', {
    params: { page, page_size: pageSize, active_only: activeOnly },
  });
  return response.data;
}

/** Create a new invite code */
export async function createInviteCode(data: CreateInviteCodeRequest): Promise<InviteCodeCreated> {
  const response = await apiClient.post<InviteCodeCreated>('/api/admin/invite-codes', data);
  return response.data;
}

/** Get a single invite code */
export async function getInviteCode(codeId: string): Promise<InviteCode> {
  const response = await apiClient.get<InviteCode>(`/api/admin/invite-codes/${codeId}`);
  return response.data;
}

/** Update an invite code */
export async function updateInviteCode(
  codeId: string,
  data: UpdateInviteCodeRequest,
): Promise<InviteCode> {
  const response = await apiClient.patch<InviteCode>(`/api/admin/invite-codes/${codeId}`, data);
  return response.data;
}

/** Toggle invite code active status */
export async function toggleInviteCode(codeId: string): Promise<InviteCode> {
  const response = await apiClient.post<InviteCode>(`/api/admin/invite-codes/${codeId}/toggle`);
  return response.data;
}

/** Delete an invite code */
export async function deleteInviteCode(codeId: string): Promise<{ success: boolean; message: string }> {
  const response = await apiClient.delete<{ success: boolean; message: string }>(
    `/api/admin/invite-codes/${codeId}`,
  );
  return response.data;
}

/** Get usage records for an invite code */
export async function getInviteCodeUsages(
  codeId: string,
  page = 1,
  pageSize = 20,
): Promise<InviteCodeUsageList> {
  const response = await apiClient.get<InviteCodeUsageList>(
    `/api/admin/invite-codes/${codeId}/usages`,
    { params: { page, page_size: pageSize } },
  );
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
  // Invite codes
  getSignupSettings,
  updateSignupSettings,
  getInviteCodeStats,
  listInviteCodes,
  createInviteCode,
  getInviteCode,
  updateInviteCode,
  toggleInviteCode,
  deleteInviteCode,
  getInviteCodeUsages,
};
