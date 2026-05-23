/**
 * Jobs API — Client for background job tracking
 */
import { apiClient } from './client';

// =============================================================================
// Types
// =============================================================================

export type JobStatusValue =
  | 'QUEUED'
  | 'RUNNING'
  | 'SUCCEEDED'
  | 'FAILED'
  | 'CANCELED';

export const TERMINAL_STATUSES: JobStatusValue[] = [
  'SUCCEEDED',
  'FAILED',
  'CANCELED',
];

export interface JobOut {
  id: string;
  job_type: string;
  status: JobStatusValue;
  progress_pct: number;
  current_step?: string | null;
  celery_task_id?: string | null;
  payload?: Record<string, unknown> | null;
  result?: Record<string, unknown> | null;
  error_message?: string | null;
  created_at: string;
  started_at?: string | null;
  finished_at?: string | null;
}

/** Response returned by all /async/* endpoints */
export interface AsyncJobResponse {
  success: boolean;
  job_id: string;
  message: string;
  status_url: string;
  stream_url: string;
}

/** Lightweight generic wrapper for task results */
export interface JobResult<T = unknown> {
  success: boolean;
  data?: T;
  error?: string;
}

export interface CancelResponse {
  success: boolean;
  message: string;
}

// =============================================================================
// API Functions
// =============================================================================

export async function getJob(jobId: string): Promise<JobOut> {
  const response = await apiClient.get<JobOut>(`/api/jobs/${jobId}`);
  return response.data;
}

export interface JobListOut {
  items: JobOut[];
  total: number;
  page: number;
  page_size: number;
  pages: number;
}

export interface ListJobsParams {
  jobType?: string;
  /** One or more backend statuses (raw enum values, e.g. ``QUEUED``,
   *  ``STARTED``, ``PROGRESS``). Sent comma-separated. */
  statuses?: string[];
  userId?: string;
  page?: number;
  pageSize?: number;
}

export async function listJobs(params: ListJobsParams = {}): Promise<JobListOut> {
  const query: Record<string, string | number> = {};
  if (params.jobType) query.job_type = params.jobType;
  if (params.statuses && params.statuses.length > 0) {
    query.status = params.statuses.join(',');
  }
  if (params.userId) query.user_id = params.userId;
  if (params.page) query.page = params.page;
  if (params.pageSize) query.page_size = params.pageSize;
  const response = await apiClient.get<JobListOut>('/api/jobs', { params: query });
  return response.data;
}

export async function cancelJob(jobId: string): Promise<CancelResponse> {
  const response = await apiClient.post<CancelResponse>(
    `/api/jobs/${jobId}/cancel`
  );
  return response.data;
}
