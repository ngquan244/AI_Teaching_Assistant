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

export async function cancelJob(jobId: string): Promise<CancelResponse> {
  const response = await apiClient.post<CancelResponse>(
    `/api/jobs/${jobId}/cancel`
  );
  return response.data;
}
