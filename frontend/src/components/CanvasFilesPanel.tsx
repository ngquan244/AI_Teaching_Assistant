import React, { useState, useEffect, useCallback, useMemo, useRef } from 'react';
import {
  FileText,
  Download,
  Loader2,
  CheckCircle,
  XCircle,
  Copy,
  RefreshCw,
  AlertCircle,
  Clock,
  Hash,
  FolderOpen,
  Database,
  BookOpen,
  Trash,
  Edit2,
  X,
  Plus,
  Save,
  ChevronDown,
  ChevronUp,
  WifiOff,
  Sparkles,
  Trash2,
} from 'lucide-react';
import PanelHelpButton from './PanelHelpButton';

/* ---------- tiny helper: random stars for background ---------- */
const generateCanvasStars = (count: number) =>
  Array.from({ length: count }, (_, i) => ({
    id: i,
    top: `${Math.random() * 100}%`,
    left: `${Math.random() * 100}%`,
    duration: `${3 + Math.random() * 4}s`,
    delay: `${Math.random() * 5}s`,
    size: `${1.5 + Math.random() * 1.5}px`,
  }));
import { useAuth } from '../context/AuthContext';
import { useConfirm } from '../context/ConfirmContext';
import { canvasApi } from '../api/canvas';
import {
  downloadCanvasFile,
  asyncIndexCanvasFile,
  asyncExtractCanvasTopics,
  listIndexedCanvasDocuments,
  listAllIndexedCanvasDocuments,
  getCanvasDocumentTopics,
  updateCanvasDocumentTopics,
  removeCanvasFileIndex,
  CanvasPermissionError,
  // V2 — course-shared domain knowledge
  listCourseDocuments,
  markDomainDocuments,
  unmarkDomainDocument,
  getPublicConfig,
  type CanvasIndexedDocument,
  type PublicConfig,
} from '../api/canvasRag';
import { getJob, listJobs, TERMINAL_STATUSES } from '../api/jobs';
import {
  getSelectedCourse,
  clearSelectedCourse,
} from '../utils/canvasStorage';
import type {
  CanvasFile,
  CanvasCourse,
  FileDownloadStatus,
} from '../types/canvas';
import CanvasCourseModal from './CanvasCourseModal';

// Helper to format file size
function formatFileSize(bytes: number): string {
  if (bytes === 0) return '0 B';
  const k = 1024;
  const sizes = ['B', 'KB', 'MB', 'GB'];
  const i = Math.floor(Math.log(bytes) / Math.log(k));
  return parseFloat((bytes / Math.pow(k, i)).toFixed(1)) + ' ' + sizes[i];
}

// Extended status type
type ExtendedFileStatus = FileDownloadStatus | 'index_queued' | 'indexing' | 'indexed' | 'extracting';

// Extended download state interface
interface ExtendedDownloadState {
  fileId: number;
  filename: string;
  status: ExtendedFileStatus;
  progress?: number;
  error?: string;
  md5Hash?: string;
}

// Status icon component
const StatusIcon: React.FC<{ status: ExtendedFileStatus }> = ({ status }) => {
  switch (status) {
    case 'queued':
      return <Clock size={16} className="status-icon queued" />;
    case 'downloading':
      return <Loader2 size={16} className="status-icon downloading spin" />;
    case 'hashing':
      return <Hash size={16} className="status-icon hashing" />;
    case 'saved':
      return <CheckCircle size={16} className="status-icon saved" />;
    case 'duplicate':
      return <Copy size={16} className="status-icon duplicate" />;
    case 'failed':
      return <XCircle size={16} className="status-icon failed" />;
    case 'index_queued':
      return <Clock size={16} className="status-icon index-queued" />;
    case 'indexing':
      return <Database size={16} className="status-icon indexing spin" />;
    case 'indexed':
      return <Database size={16} className="status-icon indexed" />;
    case 'extracting':
      return <BookOpen size={16} className="status-icon extracting spin" />;
    default:
      return null;
  }
};

// Status text
const statusLabels: Record<ExtendedFileStatus, string> = {
  queued: 'Đang chờ',
  downloading: 'Đang tải...',
  hashing: 'Đang kiểm tra...',
  saved: 'Đã lưu',
  duplicate: 'Đã có sẵn',
  failed: 'Thất bại',
  index_queued: 'Chờ xử lý...',
  indexing: 'Đang xử lý...',
  indexed: 'Đã xử lý',
  extracting: 'Đang trích xuất...',
};

// Tab type removed — single view now

const sanitizeCanvasFilename = (name: string) =>
  name.toLowerCase().replace(/[,]/g, '').replace(/\s+/g, ' ').trim();

const stripPdfExtension = (name: string) => name.replace(/\.pdf$/i, '');

// Backend strips non-alphanumeric chars (except `._- `) when saving Canvas
// downloads (see canvas_service.py:205). To match the canonical filename in
// allIndexedDocs, we must mirror that sanitization on the frontend display
// name. Without this, files with parens/brackets/&/etc. silently fail to
// match — UI shows "chưa index" while backend rejects re-index as duplicate.
const aggressiveSanitize = (name: string) =>
  name
    .toLowerCase()
    .split('')
    .map((c) => (/[a-z0-9._\- ]/.test(c) ? c : ''))
    .join('')
    .replace(/\s+/g, ' ')
    .trim();

const filenamesMatch = (left: string, right: string) => {
  const leftSanitized = sanitizeCanvasFilename(left);
  const rightSanitized = sanitizeCanvasFilename(right);
  const leftBase = stripPdfExtension(leftSanitized);
  const rightBase = stripPdfExtension(rightSanitized);

  if (
    leftSanitized === rightSanitized ||
    leftBase === rightBase ||
    leftSanitized.includes(rightBase) ||
    rightSanitized.includes(leftBase)
  ) {
    return true;
  }

  // Aggressive fallback to mirror backend's safe_filename sanitization.
  const leftAggr = stripPdfExtension(aggressiveSanitize(left));
  const rightAggr = stripPdfExtension(aggressiveSanitize(right));
  if (!leftAggr || !rightAggr) return false;
  return (
    leftAggr === rightAggr ||
    leftAggr.includes(rightAggr) ||
    rightAggr.includes(leftAggr)
  );
};

const findMatchingIndexedDoc = (
  displayName: string,
  docs: CanvasIndexedDocument[],
) => docs.find((doc) => filenamesMatch(displayName, doc.filename));

const CanvasFilesPanel: React.FC = () => {
  const { isAuthenticated, canvasTokens } = useAuth();
  const confirmDialog = useConfirm();
  const canvasStars = useMemo(() => generateCanvasStars(30), []);
  
  // Remote files state (from Canvas API)
  const [isModalOpen, setIsModalOpen] = useState(false);
  const [selectedCourse, setSelectedCourse] = useState<{
    id: number;
    name: string;
  } | null>(null);
  const [remoteFiles, setRemoteFiles] = useState<CanvasFile[]>([]);
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [canvasErrorType, setCanvasErrorType] = useState<'auth' | 'network' | 'unknown' | null>(null);
  const [isCanvasAvailable, setIsCanvasAvailable] = useState(true);
  const [downloadStates, setDownloadStates] = useState<
    Map<number, ExtendedDownloadState>
  >(new Map());
  const [isDownloading, setIsDownloading] = useState(false);

  // Indexed documents state (always available, even offline)
  const [indexedDocs, setIndexedDocs] = useState<CanvasIndexedDocument[]>([]);
  const [allIndexedDocs, setAllIndexedDocs] = useState<CanvasIndexedDocument[]>([]);
  const [indexedSectionExpanded, setIndexedSectionExpanded] = useState(true);
  const [indexedLoading, setIndexedLoading] = useState(false);

  // Action states for indexed files (extract/edit/remove)
  const [fileActionStates, setFileActionStates] = useState<Map<string, ExtendedFileStatus>>(new Map());

  // Track filenames whose index was just removed in this session. The next
  // time the user re-indexes one of these files we send `force_reindex=true`
  // so a stale cross-process registry/DB row from the recent delete cannot
  // short-circuit the worker into `already_indexed=true`.
  const recentlyRemovedRef = useRef<Set<string>>(new Set());

  // Job IDs we're already polling (either freshly enqueued or rehydrated on
  // mount). Used to prevent double-polling the same job after a refresh.
  const polledJobsRef = useRef<Set<string>>(new Set());
  
  // Pagination state
  const [remoteCurrentPage, setRemoteCurrentPage] = useState(1);
  const [indexedCurrentPage, setIndexedCurrentPage] = useState(1);
  const [indexedTotalPages, setIndexedTotalPages] = useState(1);
  const [indexedTotal, setIndexedTotal] = useState(0);
  const ITEMS_PER_PAGE = 5;

  // Edit topics modal state
  const [showEditTopicsModal, setShowEditTopicsModal] = useState(false);
  const [editingFilename, setEditingFilename] = useState('');
  const [editingTopics, setEditingTopics] = useState<string[]>([]);
  const [newTopicInput, setNewTopicInput] = useState('');
  const [editingTopicIndex, setEditingTopicIndex] = useState<number | null>(null);
  const [editingTopicValue, setEditingTopicValue] = useState('');
  const [isSavingTopics, setIsSavingTopics] = useState(false);

  // V2 — course-shared domain knowledge
  const [publicConfig, setPublicConfig] = useState<PublicConfig | null>(null);
  // Ref mirrors publicConfig state so that inline async functions (loadCourseDocuments,
  // handleToggleDomain) always read the *current* value regardless of which render
  // captured them via closure. Without this, the [selectedCourse] effect captures
  // loadCourseDocuments when publicConfig is still null and the check never passes.
  const publicConfigRef = useRef<PublicConfig | null>(null);
  const [domainTogglePending, setDomainTogglePending] = useState<Set<string>>(new Set());
  const [domainToggleError, setDomainToggleError] = useState<string | null>(null);

  useEffect(() => {
    let alive = true;
    getPublicConfig()
      .then((cfg) => {
        if (alive) {
          publicConfigRef.current = cfg;
          setPublicConfig(cfg);
        }
      })
      .catch((err) => {
        console.warn('Failed to load public config:', err);
      });
    return () => {
      alive = false;
    };
  }, []);

  // Re-enrich domain flags after both publicConfig and indexed docs are ready.
  // Fingerprint keyed off file_hashes so the effect fires once per docs change
  // and stays idempotent (enrichment does not mutate hashes).
  const lastEnrichedRef = useRef<string>('');
  useEffect(() => {
    if (!publicConfig?.enable_course_domain_docs || !selectedCourse) return;
    const hashes = [
      ...indexedDocs.map((d) => d.file_hash),
      ...allIndexedDocs.map((d) => d.file_hash),
    ];
    if (hashes.length === 0) return;
    const fingerprint = `${selectedCourse.id}|${hashes.sort().join(',')}`;
    if (lastEnrichedRef.current === fingerprint) return;
    lastEnrichedRef.current = fingerprint;
    void loadCourseDocuments(selectedCourse.id);
    // loadCourseDocuments captured fresh on each render but its only state
    // dependency is publicConfigRef (a ref). selectedCourse is read directly.
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [publicConfig, selectedCourse, indexedDocs, allIndexedDocs]);

  /** V2: load per-course documents (with language + is_course_domain) and
   *  merge into `indexedDocs` / `allIndexedDocs`. Called whenever the
   *  course view refreshes if the feature is enabled. */
  const loadCourseDocuments = async (courseId?: number) => {
    if (!courseId || !publicConfigRef.current?.enable_course_domain_docs) {
      return;
    }
    try {
      const res = await listCourseDocuments(courseId);
      if (!res.success) return;
      // Use boolean coercion for is_course_domain so `false` from backend
      // correctly overrides any stale undefined/true value on the local doc.
      const byHash = new Map(res.documents.map((d) => [d.file_hash, d]));
      const merge = (doc: CanvasIndexedDocument): CanvasIndexedDocument => {
        const enriched = byHash.get(doc.file_hash);
        if (!enriched) return doc;
        return {
          ...doc,
          language: enriched.language ?? doc.language,
          // IMPORTANT: do NOT use `??` here — backend always returns a boolean,
          // and we want `false` to overwrite stale optimistic `true` after unmark.
          is_course_domain: typeof enriched.is_course_domain === 'boolean'
            ? enriched.is_course_domain
            : doc.is_course_domain,
          marked_by_user_id: enriched.marked_by_user_id ?? doc.marked_by_user_id,
        };
      };
      setIndexedDocs((prev) => prev.map(merge));
      setAllIndexedDocs((prev) => prev.map(merge));
    } catch (err) {
      if (err instanceof CanvasPermissionError) {
        // Token missing / no access — silently skip; main flow already errors.
        return;
      }
      console.warn('Failed to load course documents:', err);
    }
  };

  /** V2: toggle a single document's course-domain mark.
   *  Uploaded (non-Canvas) docs cannot reach this UI per the binding rule. */
  const handleToggleDomain = async (
    doc: CanvasIndexedDocument,
    nextEnabled: boolean,
  ) => {
    if (!selectedCourse || !publicConfigRef.current?.enable_course_domain_docs) return;
    setDomainToggleError(null);
    setDomainTogglePending((prev) => {
      const next = new Set(prev);
      next.add(doc.file_hash);
      return next;
    });
    try {
      if (nextEnabled) {
        await markDomainDocuments(selectedCourse.id, [doc.file_hash]);
      } else {
        await unmarkDomainDocument(selectedCourse.id, doc.file_hash);
      }
      // Confirmed update (after server acknowledged). Apply locally so UI
      // stays in sync until next refresh enrichment.
      const apply = (d: CanvasIndexedDocument): CanvasIndexedDocument =>
        d.file_hash === doc.file_hash ? { ...d, is_course_domain: nextEnabled } : d;
      setIndexedDocs((prev) => prev.map(apply));
      setAllIndexedDocs((prev) => prev.map(apply));
      // Reset enrichment fingerprint so the next mount re-fetches from server
      // and we verify the mark survived the round-trip.
      lastEnrichedRef.current = '';
      // Verify backend persisted by re-fetching /courses/{id}/documents.
      try {
        const verify = await listCourseDocuments(selectedCourse.id);
        const found = verify.documents.find((d) => d.file_hash === doc.file_hash);
        if (found && found.is_course_domain !== nextEnabled) {
          console.warn(
            '[canvas-domain] backend reported a different value than what was sent',
          );
        }
      } catch (verifyErr) {
        console.warn('[canvas-domain] verify call failed', verifyErr);
      }
    } catch (err: unknown) {
      console.error('[canvas-domain] toggle API failed', err);
      const msg =
        (err as { response?: { data?: { detail?: { message?: string; error?: string } } } })
          ?.response?.data?.detail?.message ||
        (err as { response?: { data?: { detail?: { error?: string } } } })
          ?.response?.data?.detail?.error ||
        (err as Error)?.message ||
        'Không thể cập nhật trạng thái domain knowledge.';
      setDomainToggleError(msg);
    } finally {
      setDomainTogglePending((prev) => {
        const next = new Set(prev);
        next.delete(doc.file_hash);
        return next;
      });
    }
  };

  const loadAllIndexedDocs = async (courseId?: number) => {
    try {
      const docs = await listAllIndexedCanvasDocuments(courseId);
      setAllIndexedDocs(docs);
      return docs;
    } catch (err) {
      if (err instanceof CanvasPermissionError) {
        setError('Không có quyền truy cập khóa học này. Vui lòng kiểm tra Canvas token.');
      }
      console.error('Error loading all indexed docs:', err);
      return [];
    }
  };

  const refreshIndexedData = async (courseId?: number, page?: number) => {
    await Promise.all([
      loadIndexedDocs(courseId, page),
      loadAllIndexedDocs(courseId),
    ]);
    // V2: enrich with course-domain + language info (no-op when flag off).
    await loadCourseDocuments(courseId);
  };

  // Load selected course on mount
  useEffect(() => {
    const stored = getSelectedCourse();
    if (stored) {
      // Setting selectedCourse will trigger the [selectedCourse] effect
      // below which calls fetchRemoteFiles (already loads indexed docs).
      setSelectedCourse(stored);
    } else {
      // No stored course → fetchRemoteFiles won't run; still show indexed view.
      refreshIndexedData(undefined, 1);
    }
  }, []);

  // Race guard: ignore stale responses when user switches course quickly.
  const courseReqRef = useRef(0);

  // Fetch remote files when course changes.
  // NOTE: fetchRemoteFiles already loads indexed + all-indexed in parallel,
  // so we don't call refreshIndexedData here — that would double every request.
  // We still need loadCourseDocuments (V2 enrich) to merge language /
  // is_course_domain into the indexed view; that runs after fetchRemoteFiles.
  useEffect(() => {
    if (!selectedCourse) return;
    const reqId = ++courseReqRef.current;
    const courseId = selectedCourse.id;
    (async () => {
      await fetchRemoteFiles(courseId);
      if (courseReqRef.current !== reqId) return; // user switched course
      await loadCourseDocuments(courseId);
    })();
  }, [selectedCourse]);

  // Reset pagination when data changes
  useEffect(() => {
    setRemoteCurrentPage(1);
  }, [remoteFiles.length]);

  // Load indexed documents (works independently of Canvas API)
  const loadIndexedDocs = async (courseId?: number, page?: number) => {
    setIndexedLoading(true);
    try {
      const p = page ?? indexedCurrentPage;
      const indexedRes = await listIndexedCanvasDocuments(courseId, p, ITEMS_PER_PAGE);
      if (indexedRes.success) {
        setIndexedDocs(indexedRes.documents);
        setIndexedCurrentPage(indexedRes.page);
        setIndexedTotalPages(indexedRes.pages);
        setIndexedTotal(indexedRes.total);
      }
    } catch (err) {
      if (err instanceof CanvasPermissionError) {
        setError('Không có quyền truy cập khóa học này. Vui lòng kiểm tra Canvas token.');
      }
      console.error('Error loading indexed docs:', err);
    } finally {
      setIndexedLoading(false);
    }
  };

  const fetchRemoteFiles = async (courseId: number) => {
    setLoading(true);
    setError(null);
    setCanvasErrorType(null);
    setRemoteFiles([]);
    setDownloadStates(new Map());

    try {
      // Fetch remote files plus both indexed views in parallel.
      const [remoteResponse, indexedRes, allIndexed] = await Promise.all([
        canvasApi.fetchCourseFiles(courseId),
        listIndexedCanvasDocuments(courseId, 1, ITEMS_PER_PAGE),
        listAllIndexedCanvasDocuments(courseId),
      ]);

      if (!remoteResponse.success) {
        const errorMsg = remoteResponse.error || 'Failed to fetch files';
        setError(errorMsg);
        setIsCanvasAvailable(false);
        // Detect error type
        if (errorMsg.toLowerCase().includes('token') || errorMsg.toLowerCase().includes('401') || errorMsg.toLowerCase().includes('expired')) {
          setCanvasErrorType('auth');
        } else {
          setCanvasErrorType('unknown');
        }
        return;
      }

      setIsCanvasAvailable(true);
      setRemoteFiles(remoteResponse.files);
      
      // Update indexed docs
      if (indexedRes.success) {
        setIndexedDocs(indexedRes.documents);
        setIndexedCurrentPage(indexedRes.page);
        setIndexedTotalPages(indexedRes.pages);
        setIndexedTotal(indexedRes.total);
      }
      setAllIndexedDocs(allIndexed);
      
      // Set initial status for files that are already indexed anywhere in the course,
      // not just in the currently visible indexed-documents page.
      const newStates = new Map<number, ExtendedDownloadState>();
      remoteResponse.files.forEach((file: CanvasFile) => {
        if (findMatchingIndexedDoc(file.display_name, allIndexed)) {
          newStates.set(file.id, {
            fileId: file.id,
            filename: file.display_name,
            status: 'indexed',
          });
        }
      });
      
      if (newStates.size > 0) {
        setDownloadStates(newStates);
      }

      // ── Rehydrate "indexing" state from server-side Jobs ──────────────
      // After a page refresh the React-local downloadStates Map is empty,
      // but a CANVAS_INDEX_FILE job may still be in flight on the worker.
      // Look it up and resume polling so the spinner is restored.
      try {
        const live = await listJobs({
          jobType: 'CANVAS_INDEX_FILE',
          statuses: ['QUEUED', 'STARTED', 'PROGRESS'],
          pageSize: 100,
        });
        if (live.items.length > 0) {
          const filenameToFile = new Map<string, CanvasFile>();
          remoteResponse.files.forEach((f: CanvasFile) => {
            filenameToFile.set(f.display_name, f);
          });
          // Build a fuzzy-match lookup too: jobs are keyed by saved filename
          // which may differ from display_name for files with commas etc.
          const matchFile = (jobFilename: string): CanvasFile | undefined => {
            const direct = filenameToFile.get(jobFilename);
            if (direct) return direct;
            return remoteResponse.files.find((f: CanvasFile) =>
              filenamesMatch(jobFilename, f.display_name),
            );
          };

          const rehydrated = new Map(newStates);
          const toPoll: Array<{ file: CanvasFile; filename: string; jobId: string }> = [];
          for (const job of live.items) {
            const jobFilename = (job.payload as { filename?: string } | null)?.filename;
            if (!jobFilename) continue;
            const file = matchFile(jobFilename);
            if (!file) continue; // job is for a file not on the current page
            rehydrated.set(file.id, {
              fileId: file.id,
              filename: file.display_name,
              status: job.status === 'QUEUED' ? 'index_queued' : 'indexing',
            });
            toPoll.push({ file, filename: jobFilename, jobId: job.id });
          }
          if (toPoll.length > 0) {
            setDownloadStates(rehydrated);
            for (const { file, filename, jobId } of toPoll) {
              // Fire-and-forget; pollIndexJob guards against duplicate polls.
              void pollIndexJob(file.id, filename, file.display_name, jobId);
            }
          }
        }
      } catch (jobErr) {
        // Non-fatal: rehydration failure just means no spinner is shown.
        console.warn('Failed to rehydrate indexing jobs:', jobErr);
      }
    } catch (err) {
      setError('Lỗi kết nối mạng. Vui lòng kiểm tra kết nối.');
      setIsCanvasAvailable(false);
      setCanvasErrorType('network');
    } finally {
      setLoading(false);
    }
  };

  const handleCourseSelected = (course: CanvasCourse) => {
    setSelectedCourse({ id: course.id, name: course.name });
  };

  const handleChangeCourse = () => {
    setIsModalOpen(true);
  };

  const handleDisconnect = () => {
    clearSelectedCourse();
    setSelectedCourse(null);
    setRemoteFiles([]);
    setDownloadStates(new Map());
    refreshIndexedData(undefined, 1);
  };

  const updateFileStatus = useCallback(
    (fileId: number, update: Partial<ExtendedDownloadState>) => {
      setDownloadStates((prev) => {
        const newMap = new Map(prev);
        const current = newMap.get(fileId) || {
          fileId,
          filename: '',
          status: 'queued' as ExtendedFileStatus,
        };
        newMap.set(fileId, { ...current, ...update });
        return newMap;
      });
    },
    []
  );

  const downloadSingleFile = async (file: CanvasFile) => {
    if (!selectedCourse) return;

    updateFileStatus(file.id, {
      fileId: file.id,
      filename: file.display_name,
      status: 'downloading',
    });

    try {
      const result = await downloadCanvasFile({
        file_id: file.id,
        filename: file.display_name,
        url: file.url,
        course_id: selectedCourse.id,
      });

      updateFileStatus(file.id, {
        status: result.status as ExtendedFileStatus,
        md5Hash: result.md5_hash,
        error: result.error,
      });
      
      return result;
    } catch (err) {
      updateFileStatus(file.id, {
        status: 'failed',
        error: 'Download failed',
      });
      return null;
    }
  };

  /**
   * Poll a canvas_index_file job until it terminates, updating the
   * download-state UI for the matching file. Used both immediately after
   * enqueueing a new index job AND after a page refresh to rehydrate the
   * "indexing" spinner for jobs that are still in flight on the server.
   */
  const pollIndexJob = useCallback(
    async (
      fileId: number,
      filenameToIndex: string,
      displayName: string,
      jobId: string,
    ) => {
      if (polledJobsRef.current.has(jobId)) return;
      polledJobsRef.current.add(jobId);
      try {
        let jobResult = await getJob(jobId);
        while (!TERMINAL_STATUSES.includes(jobResult.status)) {
          // Transition from "waiting in queue" to "actively processing"
          if (jobResult.status === 'STARTED' || jobResult.status === 'PROGRESS') {
            updateFileStatus(fileId, { status: 'indexing' });
          }
          await new Promise((resolve) => setTimeout(resolve, 2000));
          jobResult = await getJob(jobId);
        }

        if (jobResult.status === 'SUCCEEDED' && jobResult.result) {
          const result = jobResult.result as {
            success?: boolean;
            already_indexed?: boolean;
            error?: string;
          };
          if (result.success) {
            recentlyRemovedRef.current.delete(filenameToIndex);
            recentlyRemovedRef.current.delete(displayName);
            updateFileStatus(fileId, { status: 'indexed' });
            if (!result.already_indexed) {
              await refreshIndexedData(selectedCourse?.id, 1);
              window.dispatchEvent(new CustomEvent('canvas-topics-updated'));
            }
          } else {
            updateFileStatus(fileId, {
              status: 'failed',
              error: result.error || 'Index failed',
            });
          }
        } else {
          updateFileStatus(fileId, {
            status: 'failed',
            error: jobResult.error_message || 'Index failed',
          });
        }
      } catch (err) {
        updateFileStatus(fileId, { status: 'failed', error: 'Index failed' });
      } finally {
        polledJobsRef.current.delete(jobId);
      }
    },
    // selectedCourse and updateFileStatus are stable enough; refreshIndexedData
    // closes over selectedCourse but we read selectedCourse?.id directly here
    // and refreshIndexedData itself is recreated on every render. Keeping the
    // dep list small to avoid restarting polls.
    // eslint-disable-next-line react-hooks/exhaustive-deps
    [updateFileStatus, selectedCourse?.id],
  );

  const downloadAndIndexFile = async (file: CanvasFile) => {
    if (!selectedCourse) return;

    // Download (or check if already downloaded)
    const downloadResult = await downloadSingleFile(file);
    
    if (!downloadResult?.success || downloadResult.status === 'failed') {
      return;
    }

    // Get the filename to index (either new or existing)
    const filenameToIndex = downloadResult.status === 'saved' 
      ? downloadResult.filename 
      : downloadResult.existing_filename;
    
    if (!filenameToIndex) {
      updateFileStatus(file.id, {
        status: 'failed',
        error: 'No filename to index',
      });
      return;
    }

    // Check if already indexed (for duplicates)
    if (downloadResult.status === 'duplicate') {
      // Check if this file is already in indexedDocs
      const isAlreadyIndexed = allIndexedDocs.some((doc) =>
        filenamesMatch(filenameToIndex, doc.filename),
      );
      if (isAlreadyIndexed) {
        updateFileStatus(file.id, { 
          status: 'indexed',
          md5Hash: downloadResult.md5_hash,
        });
        return;
      }
    }

    // Proceed to index via async job — show queued until worker picks it up
    updateFileStatus(file.id, { status: 'index_queued' });
    
    try {
      // Force re-index whenever we have evidence the prior index was removed:
      //   1. Session-local mark from a delete the user just performed, OR
      //   2. Local file exists (download returned 'duplicate') but the file
      //      is NOT in the current indexed list — i.e. user deleted the
      //      index in a previous session / different tab and the cross-process
      //      registry may still hold a stale entry.
      const sessionMark =
        recentlyRemovedRef.current.has(filenameToIndex) ||
        recentlyRemovedRef.current.has(file.display_name);
      const inferredFromState =
        downloadResult.status === 'duplicate' &&
        !allIndexedDocs.some((doc) => filenamesMatch(filenameToIndex, doc.filename));
      const forceReindex = sessionMark || inferredFromState;
      const asyncResp = await asyncIndexCanvasFile(
        filenameToIndex,
        selectedCourse?.id,
        forceReindex,
      );
      const jobId = asyncResp.job_id;

      // Delegate polling + final-state UI updates to the shared helper so the
      // exact same logic runs for newly-enqueued jobs AND for jobs rehydrated
      // after a page refresh.
      await pollIndexJob(file.id, filenameToIndex, file.display_name, jobId);
    } catch (err) {
      updateFileStatus(file.id, { 
        status: 'failed', 
        error: 'Index failed' 
      });
    }
  };

  const downloadAllFiles = async () => {
    if (!selectedCourse || remoteFiles.length === 0) return;

    setIsDownloading(true);

    // Initialize all files as queued
    remoteFiles.forEach((file) => {
      updateFileStatus(file.id, {
        fileId: file.id,
        filename: file.display_name,
        status: 'queued',
      });
    });

    // Download files sequentially
    for (const file of remoteFiles) {
      await downloadSingleFile(file);
    }

    setIsDownloading(false);
  };

  const downloadAndIndexAll = async () => {
    if (!selectedCourse || remoteFiles.length === 0) return;

    setIsDownloading(true);

    // Initialize all files as queued
    remoteFiles.forEach((file) => {
      updateFileStatus(file.id, {
        fileId: file.id,
        filename: file.display_name,
        status: 'queued',
      });
    });

    // Download and index files sequentially
    for (const file of remoteFiles) {
      await downloadAndIndexFile(file);
    }

    setIsDownloading(false);
    
    // Refresh indexed docs
    refreshIndexedData(selectedCourse?.id, 1);
  };

  // === File action handlers (shared by remote rows + indexed section) ===

  const handleExtractTopics = async (filename: string) => {
    setFileActionStates(prev => new Map(prev).set(filename, 'extracting'));
    
    try {
      const asyncResp = await asyncExtractCanvasTopics(filename, 10);
      const jobId = asyncResp.job_id;

      // Poll until job completes
      let jobResult = await getJob(jobId);
      while (!TERMINAL_STATUSES.includes(jobResult.status)) {
        await new Promise(resolve => setTimeout(resolve, 2000));
        jobResult = await getJob(jobId);
      }

      if (jobResult.status === 'SUCCEEDED') {
        // Job completed — but the extraction itself may still have failed
        // (e.g. Groq token exhausted). In that case the indexed document
        // is preserved (topic_count = 0) and the user can retry.
        const payload = (jobResult.result || {}) as { success?: boolean; error?: string; topics?: string[] };
        setFileActionStates(prev => {
          const newMap = new Map(prev);
          newMap.delete(filename);
          return newMap;
        });
        await refreshIndexedData(selectedCourse?.id, 1);
        window.dispatchEvent(new CustomEvent('canvas-topics-updated'));
        if (payload.success === false) {
          console.warn(
            `[extract-topics] Failed for "${filename}": ${payload.error || 'unknown error'}`,
          );
        }
      } else {
        setFileActionStates(prev => new Map(prev).set(filename, 'failed'));
        const errMsg = (jobResult as { error?: string }).error;
        console.warn(
          `[extract-topics] Job failed for "${filename}": ${errMsg || 'unknown'}`,
        );
      }
    } catch (err) {
      if (err instanceof CanvasPermissionError) {
        console.warn('[extract-topics] Canvas permission denied');
      }
      setFileActionStates(prev => new Map(prev).set(filename, 'failed'));
    }
  };

  const handleRemoveIndex = async (filename: string) => {
    const ok = await confirmDialog({
      title: 'Xóa index nội bộ?',
      message: `Xóa index nội bộ cho "${filename}"?\n\nHành động này chỉ xóa dữ liệu vector và chủ đề trên hệ thống. File trên Canvas LMS không bị ảnh hưởng.`,
      confirmLabel: 'Xóa index',
      cancelLabel: 'Hủy',
      tone: 'danger',
    });
    if (!ok) {
      return;
    }
    
    try {
      const result = await removeCanvasFileIndex(filename);
      if (result.success) {
        recentlyRemovedRef.current.add(filename);
        await refreshIndexedData(selectedCourse?.id, 1);
        window.dispatchEvent(new CustomEvent('canvas-topics-updated'));
      }
    } catch (err) {
      console.error('Error removing index:', err);
    }
  };

  // Remove index for remote file (from Canvas file list)
  const handleRemoveIndexForRemoteFile = async (file: CanvasFile) => {
    const sanitizedName = file.display_name.replace(/[,]/g, '');

    const ok = await confirmDialog({
      title: 'Xóa index nội bộ?',
      message: `Xóa index nội bộ cho "${file.display_name}"?\n\nHành động này chỉ xóa dữ liệu vector và chủ đề trên hệ thống. File trên Canvas LMS không bị ảnh hưởng.`,
      confirmLabel: 'Xóa index',
      cancelLabel: 'Hủy',
      tone: 'danger',
    });
    if (!ok) {
      return;
    }
    
    try {
      // Try with both original and sanitized name
      let result = await removeCanvasFileIndex(sanitizedName);
      if (!result.success) {
        result = await removeCanvasFileIndex(file.display_name);
      }

      if (result.success) {
        recentlyRemovedRef.current.add(file.display_name);
        recentlyRemovedRef.current.add(sanitizedName);
        // Reset status — no longer indexed
        setDownloadStates(prev => {
          const newMap = new Map(prev);
          newMap.delete(file.id);
          return newMap;
        });
        await refreshIndexedData(selectedCourse?.id, 1);
        window.dispatchEvent(new CustomEvent('canvas-topics-updated'));
      }
    } catch (err) {
      console.error('Error removing index:', err);
    }
  };

  // Edit topics modal handlers
  const openEditTopicsModal = async (filename: string) => {
    try {
      const response = await getCanvasDocumentTopics(filename);
      setEditingFilename(filename);
      setEditingTopics(response.topics || []);
      setNewTopicInput('');
      setEditingTopicIndex(null);
      setShowEditTopicsModal(true);
    } catch (err) {
      if (err instanceof CanvasPermissionError) {
        alert('Không có quyền truy cập khóa học này. Vui lòng kiểm tra Canvas token.');
      }
      console.error('Error loading topics:', err);
    }
  };

  const closeEditTopicsModal = () => {
    setShowEditTopicsModal(false);
    setEditingFilename('');
    setEditingTopics([]);
  };

  const addNewTopic = () => {
    const trimmed = newTopicInput.trim();
    if (trimmed && !editingTopics.includes(trimmed)) {
      setEditingTopics([...editingTopics, trimmed]);
      setNewTopicInput('');
    }
  };

  const removeTopic = (index: number) => {
    setEditingTopics(editingTopics.filter((_, i) => i !== index));
  };

  const startEditTopic = (index: number) => {
    setEditingTopicIndex(index);
    setEditingTopicValue(editingTopics[index]);
  };

  const saveEditTopic = () => {
    if (editingTopicIndex !== null && editingTopicValue.trim()) {
      const updated = [...editingTopics];
      updated[editingTopicIndex] = editingTopicValue.trim();
      setEditingTopics(updated);
    }
    setEditingTopicIndex(null);
    setEditingTopicValue('');
  };

  const cancelEditTopic = () => {
    setEditingTopicIndex(null);
    setEditingTopicValue('');
  };

  const saveTopicsToBackend = async () => {
    if (!editingFilename) return;
    
    setIsSavingTopics(true);
    try {
      const response = await updateCanvasDocumentTopics(editingFilename, editingTopics);
      
      if (response.success) {
        closeEditTopicsModal();
        await refreshIndexedData(selectedCourse?.id, 1);
        window.dispatchEvent(new CustomEvent('canvas-topics-updated'));
      } else {
        alert('Không thể lưu chủ đề. Vui lòng thử lại.');
      }
    } catch (error) {
      console.error('Error saving topics:', error);
      if (error instanceof CanvasPermissionError) {
        alert('Không có quyền truy cập khóa học này. Vui lòng kiểm tra Canvas token.');
      } else {
        alert('Lỗi khi lưu chủ đề.');
      }
    } finally {
      setIsSavingTopics(false);
    }
  };

  const getDownloadSummary = () => {
    const states = Array.from(downloadStates.values());
    return {
      total: states.length,
      saved: states.filter((s) => s.status === 'saved').length,
      indexed: states.filter((s) => s.status === 'indexed').length,
      duplicates: states.filter((s) => s.status === 'duplicate').length,
      failed: states.filter((s) => s.status === 'failed').length,
      pending: states.filter((s) =>
        ['queued', 'downloading', 'hashing', 'index_queued', 'indexing', 'extracting'].includes(s.status)
      ).length,
    };
  };

  const isConfigured = isAuthenticated && canvasTokens.length > 0;

  if (!isConfigured) {
    return (
      <div className="canvas-panel">
        {/* Decorative background */}
        <div className="canvas-bg-decoration">
          <div className="canvas-bg-orb canvas-bg-orb-1" />
          <div className="canvas-bg-orb canvas-bg-orb-2" />
          <div className="canvas-bg-orb canvas-bg-orb-3" />
        </div>
        <div className="canvas-stars">
          {canvasStars.map((s) => (
            <span
              key={s.id}
              className="canvas-star"
              style={{ top: s.top, left: s.left, '--duration': s.duration, '--delay': s.delay, width: s.size, height: s.size } as React.CSSProperties}
            />
          ))}
        </div>
        <div className="canvas-glow-line canvas-glow-line-1" />
        <div className="canvas-glow-line canvas-glow-line-2" />

        <div className="canvas-hero-header">
          <div className="canvas-hero-icon">
            <FolderOpen size={28} />
          </div>
          <div className="canvas-hero-text">
            <h2>Canvas LMS</h2>
            <p>Tải file từ Canvas, index và quản lý tài liệu</p>
          </div>
          <PanelHelpButton panelKey="canvas" />
        </div>
        <div className="canvas-not-configured">
          <AlertCircle size={48} />
          <h3>Canvas Not Configured</h3>
          <p>
            {!isAuthenticated 
              ? 'Please login first to access Canvas integration.'
              : 'Please add your Canvas access token in Settings first.'}
          </p>
        </div>
      </div>
    );
  }

  return (
    <div className="canvas-panel">
      {/* ---- Decorative background (matching RAG panel) ---- */}
      <div className="canvas-bg-decoration">
        <div className="canvas-bg-orb canvas-bg-orb-1" />
        <div className="canvas-bg-orb canvas-bg-orb-2" />
        <div className="canvas-bg-orb canvas-bg-orb-3" />
      </div>
      <div className="canvas-stars">
        {canvasStars.map((s) => (
          <span
            key={s.id}
            className="canvas-star"
            style={{ top: s.top, left: s.left, '--duration': s.duration, '--delay': s.delay, width: s.size, height: s.size } as React.CSSProperties}
          />
        ))}
      </div>
      <div className="canvas-glow-line canvas-glow-line-1" />
      <div className="canvas-glow-line canvas-glow-line-2" />

      <div className="canvas-hero-header">
        <div className="canvas-hero-icon">
          <FolderOpen size={28} />
        </div>
        <div className="canvas-hero-text">
          <h2>Canvas LMS</h2>
          <p>Tải file từ Canvas, index và quản lý tài liệu</p>
        </div>
        <PanelHelpButton panelKey="canvas" />
      </div>

      <div className="canvas-content">

      {/* Offline Banner */}
      {!isCanvasAvailable && selectedCourse && (
        <div className="canvas-offline-banner">
          <WifiOff size={18} />
          <div className="offline-text">
            <strong>Chế độ offline</strong>
            <span>
              {canvasErrorType === 'auth'
                ? 'Token Canvas không hợp lệ hoặc đã hết hạn. Vui lòng cập nhật token trong Cài đặt.'
                : canvasErrorType === 'network'
                ? 'Không thể kết nối Canvas LMS. Kiểm tra kết nối mạng.'
                : 'Không thể truy cập Canvas LMS.'}
              {' '}Quản lý tài liệu đã index vẫn khả dụng.
            </span>
          </div>
          <button
            className="btn-secondary btn-sm"
            onClick={() => selectedCourse && fetchRemoteFiles(selectedCourse.id)}
            disabled={loading}
          >
            <RefreshCw size={14} className={loading ? 'spin' : ''} />
            Thử lại
          </button>
        </div>
      )}

      {/* Course Selection Section */}
      <div className="canvas-section">
        <h3>Khóa học đã chọn</h3>
        {selectedCourse ? (
          <div className="selected-course">
            <div className="course-details">
              <span className="course-name">{selectedCourse.name}</span>
              <span className="course-id">ID: {selectedCourse.id}</span>
            </div>
            <div className="course-actions">
              <button className="btn-secondary btn-sm" onClick={handleChangeCourse}>
                Đổi
              </button>
              <button
                className="btn-secondary btn-sm danger"
                onClick={handleDisconnect}
              >
                Ngắt kết nối
              </button>
            </div>
          </div>
        ) : (
          <button className="btn-primary" onClick={() => setIsModalOpen(true)}>
            <FolderOpen size={18} />
            Chọn khóa học
          </button>
        )}
      </div>

      {/* Files Section */}
          {selectedCourse && isCanvasAvailable && (
            <div className="canvas-section">
              <div className="section-header">
                <h3>File trong khóa học</h3>
                <div className="section-actions">
                  <button
                    className="btn-secondary btn-sm"
                    onClick={() => fetchRemoteFiles(selectedCourse.id)}
                    disabled={loading}
                  >
                    <RefreshCw size={16} className={loading ? 'spin' : ''} />
                    Refresh
                  </button>
                  <button
                    className="btn-secondary btn-sm"
                    onClick={downloadAllFiles}
                    disabled={loading || isDownloading || remoteFiles.length === 0}
                  >
                    <Download size={16} />
                    Tải tất cả
                  </button>
                  <button
                    className="btn-primary btn-sm"
                    onClick={downloadAndIndexAll}
                    disabled={loading || isDownloading || remoteFiles.length === 0}
                  >
                    <Database size={16} />
                    Tải & Index
                  </button>
                </div>
              </div>

              {/* Download Summary */}
              {downloadStates.size > 0 && (
                <div className="download-summary">
                  {(() => {
                    const summary = getDownloadSummary();
                    return (
                      <>
                        <span className="summary-item indexed">
                          <Database size={14} /> {summary.indexed} indexed
                        </span>
                        <span className="summary-item saved">
                          <CheckCircle size={14} /> {summary.saved} saved
                        </span>
                        <span className="summary-item duplicate">
                          <Copy size={14} /> {summary.duplicates} duplicates
                        </span>
                        <span className="summary-item failed">
                          <XCircle size={14} /> {summary.failed} failed
                        </span>
                        {summary.pending > 0 && (
                          <span className="summary-item pending">
                            <Loader2 size={14} className="spin" /> {summary.pending} pending
                          </span>
                        )}
                      </>
                    );
                  })()}
                </div>
              )}

              {/* Loading State */}
              {loading && (
                <div className="loading-center">
                  <Loader2 className="spin" size={32} />
                </div>
              )}

              {/* Error State */}
              {error && (
                <div className="result-message error">
                  <AlertCircle size={20} />
                  {error}
                </div>
              )}

              {/* Files List with Pagination */}
              {!loading && !error && (() => {
                const totalPages = Math.max(1, Math.ceil(remoteFiles.length / ITEMS_PER_PAGE));
                const startIndex = (remoteCurrentPage - 1) * ITEMS_PER_PAGE;
                const paginatedFiles = remoteFiles.slice(startIndex, startIndex + ITEMS_PER_PAGE);
                
                return (
                  <>
                    <div className="files-list">
                      <table className="files-table">
                        <thead>
                          <tr>
                            <th>Tên file</th>
                            <th>Kích thước</th>
                            <th>Trạng thái</th>
                            <th>Thao tác</th>
                          </tr>
                        </thead>
                        <tbody>
                          {paginatedFiles.length > 0 ? (
                            paginatedFiles.map((file) => {
                              const state = downloadStates.get(file.id);
                              const indexedDoc = findMatchingIndexedDoc(file.display_name, allIndexedDocs);
                              const isIndexed = state?.status === 'indexed' || Boolean(indexedDoc);
                              // Filename used for extract/edit actions. Falls back to a sanitized
                              // display_name when the document is indexed but missing from
                              // allIndexedDocs (e.g. /indexed endpoint filtered it out due to a
                              // transient Canvas-permission check failure).
                              const actionFilename = indexedDoc?.filename || file.display_name.replace(/[,]/g, '');
                              const actionState = fileActionStates.get(actionFilename);
                              const topicCount = indexedDoc?.topic_count ?? 0;
                              return (
                                <tr key={file.id}>
                                  <td>
                                    <div className="file-name">
                                      <FileText size={16} />
                                      <span>{file.display_name}</span>
                                    </div>
                                  </td>
                                  <td>{formatFileSize(file.size)}</td>
                                  <td>
                                    {actionState ? (
                                      <div className={`file-status ${actionState}`}>
                                        <StatusIcon status={actionState} />
                                        <span>{statusLabels[actionState]}</span>
                                      </div>
                                    ) : state ? (
                                      <div className={`file-status ${state.status}`}>
                                        <StatusIcon status={state.status} />
                                        <span>
                                          {statusLabels[state.status]}
                                          {isIndexed && ` · ${topicCount} chủ đề`}
                                        </span>
                                      </div>
                                    ) : (
                                      <span className="file-status idle">—</span>
                                    )}
                                  </td>
                                  <td>
                                    <div className="action-buttons">
                                      {/* Not indexed: download / download+index */}
                                      {!isIndexed && (
                                        <>
                                          <button
                                            className="btn-action"
                                            onClick={() => downloadAndIndexFile(file)}
                                            disabled={isDownloading || ['downloading', 'index_queued', 'indexing'].includes(state?.status || '')}
                                            title="Tải & Index"
                                          >
                                            <Database size={14} />
                                          </button>
                                        </>
                                      )}
                                      {/* Indexed: extract topics, edit topics, remove index.
                                          We render these even when indexedDoc is missing, using
                                          the sanitized filename, so a transient list-filter
                                          mismatch does not strip the user's controls. */}
                                      {isIndexed && (
                                        <>
                                          <button
                                            className="btn-action"
                                            onClick={() => handleExtractTopics(actionFilename)}
                                            disabled={actionState === 'extracting'}
                                            title={topicCount === 0 ? 'Trích xuất chủ đề (chưa có)' : 'Trích xuất lại chủ đề'}
                                          >
                                            <Sparkles size={14} />
                                          </button>
                                          {indexedDoc && (
                                            <button
                                              className="btn-action"
                                              onClick={() => openEditTopicsModal(indexedDoc.filename)}
                                              title="Sửa chủ đề"
                                            >
                                              <Edit2 size={14} />
                                            </button>
                                          )}
                                          <button
                                            className="btn-action warning"
                                            onClick={() => handleRemoveIndexForRemoteFile(file)}
                                            title="Xóa index nội bộ (không ảnh hưởng Canvas)"
                                          >
                                            <Trash size={14} />
                                          </button>
                                        </>
                                      )}
                                    </div>
                                  </td>
                                </tr>
                              );
                            })
                          ) : (
                            <tr>
                              <td colSpan={4} className="empty-table-message">
                                Không có file nào trong khóa học này.
                              </td>
                            </tr>
                          )}
                        </tbody>
                      </table>
                    </div>
                    
                    {/* Pagination */}
                    <div className="pagination pagination--compact">
                      <button
                        className="pagination-btn"
                        onClick={() => setRemoteCurrentPage(p => Math.max(1, p - 1))}
                        disabled={remoteCurrentPage === 1}
                      >
                        ‹ Trước
                      </button>
                      <span className="pagination-info">
                        Trang {remoteCurrentPage} / {Math.max(totalPages, 1)}
                      </span>
                      <button
                        className="pagination-btn"
                        onClick={() => setRemoteCurrentPage(p => Math.min(totalPages, p + 1))}
                        disabled={remoteCurrentPage === totalPages}
                      >
                        Sau ›
                      </button>
                    </div>
                  </>
                );
              })()}
            </div>
          )}

      {/* ===== Indexed Documents Section (always visible, works offline) ===== */}
      <div className="canvas-section indexed-documents-section">
        <div
          className="section-header clickable"
          onClick={() => setIndexedSectionExpanded(!indexedSectionExpanded)}
        >
          <h3>
            <Database size={18} />
            Tài liệu đã Index
            <span className="indexed-count-badge">{indexedTotal}</span>
          </h3>
          <div className="section-actions">
            <button
              className="btn-secondary btn-sm"
              onClick={(e) => {
                e.stopPropagation();
                refreshIndexedData(selectedCourse?.id, 1);
              }}
              disabled={indexedLoading}
            >
              <RefreshCw size={14} className={indexedLoading ? 'spin' : ''} />
            </button>
            {indexedSectionExpanded ? <ChevronUp size={18} /> : <ChevronDown size={18} />}
          </div>
        </div>

        {indexedSectionExpanded && (
          <>
            {indexedLoading && (
              <div className="loading-center">
                <Loader2 className="spin" size={24} />
              </div>
            )}

            {!indexedLoading && (() => {
              const showDomainCols = !!publicConfig?.enable_course_domain_docs && !!selectedCourse;
              const totalCols = showDomainCols ? 6 : 4;
              return (
                <>
                  {showDomainCols && (
                    <div
                      className="info-banner"
                      style={{
                        margin: '0 0 12px',
                        padding: '8px 12px',
                        borderRadius: 6,
                        background: 'rgba(56, 189, 248, 0.08)',
                        border: '1px solid rgba(56, 189, 248, 0.3)',
                        color: '#7dd3fc',
                        fontSize: 12,
                        lineHeight: 1.45,
                      }}
                    >
                      <strong>Course-shared domain knowledge</strong> is available
                      only for indexed Canvas course documents. Uploaded personal
                      documents cannot be marked.
                    </div>
                  )}
                  {showDomainCols && domainToggleError && (
                    <div
                      className="error-banner"
                      style={{
                        margin: '0 0 12px',
                        padding: '8px 12px',
                        borderRadius: 6,
                        background: 'rgba(248, 113, 113, 0.10)',
                        border: '1px solid rgba(248, 113, 113, 0.4)',
                        color: '#fca5a5',
                        fontSize: 12,
                      }}
                    >
                      {domainToggleError}
                    </div>
                  )}
                  <div className="files-list">
                    <table className="files-table">
                      <thead>
                        <tr>
                          <th>Tên file</th>
                          <th>Chunks</th>
                          <th>Topics</th>
                          {showDomainCols && <th>Domain</th>}
                          <th>Thao tác</th>
                        </tr>
                      </thead>
                      <tbody>
                        {indexedDocs.length > 0 ? (
                          indexedDocs.map((doc) => {
                            const actionState = fileActionStates.get(doc.filename);
                            const togglePending = domainTogglePending.has(doc.file_hash);
                            return (
                              <tr key={doc.file_hash}>
                                <td>
                                  <div className="file-name">
                                    <FileText size={16} />
                                    <span>{doc.filename}</span>
                                  </div>
                                </td>
                                <td>
                                  <span className="chunk-count">{doc.chunks_added}</span>
                                </td>
                                <td>
                                  <span className={`topic-count ${doc.topic_count === 0 ? 'empty' : ''}`}>
                                    {doc.topic_count > 0 ? `${doc.topic_count} topics` : '—'}
                                  </span>
                                </td>
                                {showDomainCols && (
                                  <td>
                                    <label
                                      style={{
                                        display: 'inline-flex',
                                        alignItems: 'center',
                                        gap: 6,
                                        cursor: togglePending ? 'wait' : 'pointer',
                                        opacity: togglePending ? 0.6 : 1,
                                      }}
                                      title={
                                        doc.is_course_domain
                                          ? 'Currently shared with the course. Click to unmark.'
                                          : 'Click to share this Canvas document with the entire course.'
                                      }
                                    >
                                      <input
                                        type="checkbox"
                                        checked={!!doc.is_course_domain}
                                        disabled={togglePending}
                                        onChange={(e) =>
                                          handleToggleDomain(doc, e.target.checked)
                                        }
                                      />
                                      <span style={{ fontSize: 11, color: '#94a3b8' }}>
                                        {doc.is_course_domain ? 'Shared' : 'Personal'}
                                      </span>
                                    </label>
                                  </td>
                                )}
                                <td>
                                  <div className="action-buttons">
                                    {actionState ? (
                                      <div className={`file-status ${actionState}`}>
                                        <StatusIcon status={actionState} />
                                      </div>
                                    ) : (
                                      <>
                                        <button
                                          className="btn-action"
                                          onClick={() => handleExtractTopics(doc.filename)}
                                          title="Trích xuất chủ đề"
                                        >
                                          <Sparkles size={14} />
                                        </button>
                                        <button
                                          className="btn-action"
                                          onClick={() => openEditTopicsModal(doc.filename)}
                                          title="Sửa chủ đề"
                                        >
                                          <Edit2 size={14} />
                                        </button>
                                        <button
                                          className="btn-action warning"
                                          onClick={() => handleRemoveIndex(doc.filename)}
                                          title="Xóa index nội bộ (không ảnh hưởng Canvas)"
                                        >
                                          <Trash2 size={14} />
                                        </button>
                                      </>
                                    )}
                                  </div>
                                </td>
                              </tr>
                            );
                          })
                        ) : (
                          <tr>
                            <td colSpan={totalCols} className="empty-table-message">
                              Chưa có tài liệu nào được index.
                            </td>
                          </tr>
                        )}
                      </tbody>
                    </table>
                  </div>

                  {/* Pagination */}
                  {indexedTotalPages > 1 && (
                    <div className="pagination pagination--compact">
                      <button
                        className="pagination-btn"
                        onClick={() => loadIndexedDocs(selectedCourse?.id, indexedCurrentPage - 1)}
                        disabled={indexedCurrentPage <= 1}
                      >
                        ‹ Trước
                      </button>
                      <span className="pagination-info">
                        Trang {indexedCurrentPage} / {indexedTotalPages}
                      </span>
                      <button
                        className="pagination-btn"
                        onClick={() => loadIndexedDocs(selectedCourse?.id, indexedCurrentPage + 1)}
                        disabled={indexedCurrentPage >= indexedTotalPages}
                      >
                        Sau ›
                      </button>
                    </div>
                  )}
                </>
              );
            })()}
          </>
        )}
      </div>

      </div>{/* end canvas-content */}

      {/* Course Selection Modal — rendered outside canvas-content so it stacks above hero header */}
      <CanvasCourseModal
        isOpen={isModalOpen}
        onClose={() => setIsModalOpen(false)}
        onCourseSelected={handleCourseSelected}
      />

      {/* Edit Topics Modal — also outside canvas-content for proper z-stacking */}
      {showEditTopicsModal && (
        <div className="modal-overlay edit-topics-overlay" onClick={closeEditTopicsModal}>
          <div className="edit-topics-modal" onClick={e => e.stopPropagation()}>
            <div className="modal-header">
              <h3>
                <Edit2 size={20} />
                Sửa chủ đề - {editingFilename}
              </h3>
              <button className="modal-close" onClick={closeEditTopicsModal}>
                <X size={16} />
                <span>Đóng</span>
              </button>
            </div>
            
            <div className="modal-body edit-topics-body">
              {/* Add new topic */}
              <div className="add-topic-section">
                <label>Thêm chủ đề mới</label>
                <div className="add-topic-input-group">
                  <input
                    type="text"
                    value={newTopicInput}
                    onChange={(e) => setNewTopicInput(e.target.value)}
                    onKeyPress={(e) => e.key === 'Enter' && addNewTopic()}
                    placeholder="Nhập tên chủ đề..."
                    className="add-topic-input"
                  />
                  <button
                    type="button"
                    className="btn-add-topic"
                    onClick={addNewTopic}
                    disabled={!newTopicInput.trim()}
                  >
                    <Plus size={18} />
                    Thêm
                  </button>
                </div>
              </div>

              {/* Topics list */}
              <div className="edit-topics-list">
                <label>Danh sách chủ đề ({editingTopics.length})</label>
                {editingTopics.length === 0 ? (
                  <div className="no-topics-message">
                    <AlertCircle size={16} />
                    <span>Chưa có chủ đề nào. Hãy thêm chủ đề mới.</span>
                  </div>
                ) : (
                  <div className="topics-edit-grid">
                    {editingTopics.map((topic, idx) => (
                      <div key={idx} className="topic-edit-item">
                        {editingTopicIndex === idx ? (
                          <div className="topic-edit-inline">
                            <input
                              type="text"
                              value={editingTopicValue}
                              onChange={(e) => setEditingTopicValue(e.target.value)}
                              onKeyPress={(e) => e.key === 'Enter' && saveEditTopic()}
                              className="topic-edit-input"
                              autoFocus
                            />
                            <button className="btn-save-edit" onClick={saveEditTopic}>
                              <CheckCircle size={14} />
                              <span>Lưu</span>
                            </button>
                            <button className="btn-cancel-edit" onClick={cancelEditTopic}>
                              <X size={14} />
                              <span>Hủy</span>
                            </button>
                          </div>
                        ) : (
                          <>
                            <span className="topic-number">{idx + 1}</span>
                            <span className="topic-name">{topic}</span>
                            <div className="topic-actions">
                              <button 
                                className="btn-edit-topic" 
                                onClick={() => startEditTopic(idx)}
                                title="Sửa"
                              >
                                <Edit2 size={14} />
                                <span>Sửa</span>
                              </button>
                              <button 
                                className="btn-delete-topic" 
                                onClick={() => removeTopic(idx)}
                                title="Xóa"
                              >
                                <Trash2 size={14} />
                                <span>Xóa</span>
                              </button>
                            </div>
                          </>
                        )}
                      </div>
                    ))}
                  </div>
                )}
              </div>
            </div>
            
            <div className="modal-footer">
              <button className="btn btn-secondary" onClick={closeEditTopicsModal}>
                Hủy
              </button>
              <button 
                className="btn btn-primary" 
                onClick={saveTopicsToBackend}
                disabled={isSavingTopics}
              >
                {isSavingTopics ? (
                  <>
                    <Loader2 size={16} className="spin" />
                    Đang lưu...
                  </>
                ) : (
                  <>
                    <Save size={16} />
                    Lưu thay đổi
                  </>
                )}
              </button>
            </div>
          </div>
        </div>
      )}
    </div>
  );
};

export default CanvasFilesPanel;
