/**
 * useAsyncJob — Custom hook for Celery background job tracking with polling.
 *
 * Features:
 * - Polls GET /api/jobs/{jobId} every 2s until terminal state
 * - Delayed progress display (default 800ms) to avoid modal flicker on fast jobs
 * - sessionStorage persistence for reload resilience
 * - Queued timeout warning when worker may not be running
 * - Cleanup on unmount
 */
import { useState, useEffect, useRef, useCallback } from 'react';
import {
  getJob,
  cancelJob as cancelJobApi,
  TERMINAL_STATUSES,
  type JobOut,
  type AsyncJobResponse,
  type JobStatusValue,
} from '../api/jobs';

// =============================================================================
// Types
// =============================================================================

export interface UseAsyncJobOptions {
  /** Delay (ms) before showing progress UI. Default 800. */
  showProgressDelay?: number;
  /** Polling interval (ms). Default 2000. */
  pollInterval?: number;
  /** Timeout (ms) for QUEUED status before warning. Default 30000. */
  queuedTimeout?: number;
  /** sessionStorage key for resume. Default 'activeJob'. */
  storageKey?: string;
}

export interface UseAsyncJobReturn {
  /** Kick off an async job. Pass the API call that returns AsyncJobResponse. */
  startJob: (apiCall: () => Promise<AsyncJobResponse>) => Promise<void>;
  /** Current job state (null if no job). */
  job: JobOut | null;
  /** True while waiting for result (includes pre-modal delay). */
  isLoading: boolean;
  /** True only after showProgressDelay has elapsed and job is still running. */
  showProgress: boolean;
  /** Error message if job failed or API error. */
  error: string | null;
  /** True if job stuck in QUEUED beyond queuedTimeout. */
  queuedWarning: boolean;
  /** Cancel the current job. */
  cancel: () => Promise<void>;
  /** Clear completed/failed state to reset the hook. */
  reset: () => void;
}

interface StoredJob {
  jobId: string;
  jobType: string;
  title: string;
}

// =============================================================================
// Hook
// =============================================================================

export function useAsyncJob(options?: UseAsyncJobOptions): UseAsyncJobReturn {
  const {
    showProgressDelay = 800,
    pollInterval = 2000,
    queuedTimeout = 30000,
    storageKey = 'activeJob',
  } = options ?? {};

  const [job, setJob] = useState<JobOut | null>(null);
  const [isLoading, setIsLoading] = useState(false);
  const [showProgress, setShowProgress] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [queuedWarning, setQueuedWarning] = useState(false);

  const pollRef = useRef<ReturnType<typeof setInterval> | null>(null);
  const delayRef = useRef<ReturnType<typeof setTimeout> | null>(null);
  const queuedRef = useRef<ReturnType<typeof setTimeout> | null>(null);
  const mountedRef = useRef(true);
  const jobIdRef = useRef<string | null>(null);

  // ---------------------------------------------------------------------------
  // Cleanup helpers
  // ---------------------------------------------------------------------------

  const clearTimers = useCallback(() => {
    if (pollRef.current) {
      clearInterval(pollRef.current);
      pollRef.current = null;
    }
    if (delayRef.current) {
      clearTimeout(delayRef.current);
      delayRef.current = null;
    }
    if (queuedRef.current) {
      clearTimeout(queuedRef.current);
      queuedRef.current = null;
    }
  }, []);

  const clearStorage = useCallback(() => {
    try {
      sessionStorage.removeItem(storageKey);
    } catch {
      // Ignore storage errors
    }
  }, [storageKey]);

  const saveToStorage = useCallback(
    (jobId: string, jobType: string, title: string) => {
      try {
        const data: StoredJob = { jobId, jobType, title };
        sessionStorage.setItem(storageKey, JSON.stringify(data));
      } catch {
        // Ignore storage errors
      }
    },
    [storageKey]
  );

  // ---------------------------------------------------------------------------
  // Poll logic
  // ---------------------------------------------------------------------------

  const startPolling = useCallback(
    (jobId: string) => {
      jobIdRef.current = jobId;

      const poll = async () => {
        if (!mountedRef.current) return;

        try {
          const freshJob = await getJob(jobId);
          if (!mountedRef.current) return;

          setJob(freshJob);

          if (TERMINAL_STATUSES.includes(freshJob.status)) {
            clearTimers();
            clearStorage();
            setIsLoading(false);
            setShowProgress(false);
            setQueuedWarning(false);

            if (freshJob.status === 'FAILED') {
              setError(freshJob.error_message || 'Job failed');
            }
          }
        } catch {
          // Network error — keep polling, don't crash
        }
      };

      // Initial fetch immediately
      poll();

      // Continue polling
      pollRef.current = setInterval(poll, pollInterval);

      // Delayed progress display
      delayRef.current = setTimeout(() => {
        if (mountedRef.current) {
          setShowProgress(true);
        }
      }, showProgressDelay);

      // Queued timeout warning
      queuedRef.current = setTimeout(() => {
        if (!mountedRef.current) return;
        // Only warn if still in QUEUED
        setQueuedWarning(true);
      }, queuedTimeout);
    },
    [pollInterval, showProgressDelay, queuedTimeout, clearTimers, clearStorage]
  );

  // ---------------------------------------------------------------------------
  // Public API
  // ---------------------------------------------------------------------------

  const startJob = useCallback(
    async (apiCall: () => Promise<AsyncJobResponse>) => {
      // Reset state
      clearTimers();
      setJob(null);
      setError(null);
      setShowProgress(false);
      setQueuedWarning(false);
      setIsLoading(true);

      try {
        const response = await apiCall();

        if (!response.success || !response.job_id) {
          setIsLoading(false);
          setError('Failed to create job');
          return;
        }

        saveToStorage(response.job_id, '', response.message);
        startPolling(response.job_id);
      } catch (err: unknown) {
        setIsLoading(false);
        const msg =
          err instanceof Error ? err.message : 'Failed to start job';
        setError(msg);
      }
    },
    [clearTimers, saveToStorage, startPolling]
  );

  const cancel = useCallback(async () => {
    if (!jobIdRef.current) return;

    try {
      await cancelJobApi(jobIdRef.current);
      // Polling will pick up the CANCELED status
    } catch {
      // Ignore cancel errors — poll will reflect status
    }
  }, []);

  const reset = useCallback(() => {
    clearTimers();
    clearStorage();
    setJob(null);
    setIsLoading(false);
    setShowProgress(false);
    setError(null);
    setQueuedWarning(false);
    jobIdRef.current = null;
  }, [clearTimers, clearStorage]);

  // ---------------------------------------------------------------------------
  // Resume from sessionStorage on mount
  // ---------------------------------------------------------------------------

  useEffect(() => {
    mountedRef.current = true;

    try {
      const raw = sessionStorage.getItem(storageKey);
      if (raw) {
        const stored: StoredJob = JSON.parse(raw);
        if (stored.jobId) {
          setIsLoading(true);
          startPolling(stored.jobId);
        }
      }
    } catch {
      // Ignore parse errors
    }

    return () => {
      mountedRef.current = false;
      clearTimers();
    };
  }, []); // eslint-disable-line react-hooks/exhaustive-deps

  // Clear queued warning when job transitions out of QUEUED
  useEffect(() => {
    if (job && job.status !== 'QUEUED' as JobStatusValue) {
      setQueuedWarning(false);
      if (queuedRef.current) {
        clearTimeout(queuedRef.current);
        queuedRef.current = null;
      }
    }
  }, [job]);

  return {
    startJob,
    job,
    isLoading,
    showProgress,
    error,
    queuedWarning,
    cancel,
    reset,
  };
}
