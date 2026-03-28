import React, { useState, useEffect, useCallback, useMemo } from 'react';
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
  ChevronLeft,
  ChevronRight,
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
import { canvasApi } from '../api/canvas';
import {
  downloadCanvasFile,
  asyncIndexCanvasFile,
  extractCanvasTopics,
  listIndexedCanvasDocuments,
  listAllIndexedCanvasDocuments,
  getCanvasDocumentTopics,
  updateCanvasDocumentTopics,
  removeCanvasFileIndex,
  CanvasPermissionError,
  type CanvasIndexedDocument,
} from '../api/canvasRag';
import { getJob, TERMINAL_STATUSES } from '../api/jobs';
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
type ExtendedFileStatus = FileDownloadStatus | 'indexing' | 'indexed' | 'extracting';

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
  indexing: 'Đang xử lý...',
  indexed: 'Đã xử lý',
  extracting: 'Đang trích xuất...',
};

// Tab type removed — single view now

const sanitizeCanvasFilename = (name: string) =>
  name.toLowerCase().replace(/[,]/g, '').replace(/\s+/g, ' ').trim();

const stripPdfExtension = (name: string) => name.replace(/\.pdf$/i, '');

const filenamesMatch = (left: string, right: string) => {
  const leftSanitized = sanitizeCanvasFilename(left);
  const rightSanitized = sanitizeCanvasFilename(right);
  const leftBase = stripPdfExtension(leftSanitized);
  const rightBase = stripPdfExtension(rightSanitized);

  return (
    leftSanitized === rightSanitized ||
    leftBase === rightBase ||
    leftSanitized.includes(rightBase) ||
    rightSanitized.includes(leftBase)
  );
};

const findMatchingIndexedDoc = (
  displayName: string,
  docs: CanvasIndexedDocument[],
) => docs.find((doc) => filenamesMatch(displayName, doc.filename));

const CanvasFilesPanel: React.FC = () => {
  const { isAuthenticated, canvasTokens } = useAuth();
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

  const loadAllIndexedDocs = async (courseId?: number) => {
    try {
      const docs = await listAllIndexedCanvasDocuments(courseId);
      setAllIndexedDocs(docs);
      return docs;
    } catch (err) {
      if (err instanceof CanvasPermissionError) {
        setError('KhÃ´ng cÃ³ quyá»n truy cáº­p khÃ³a há»c nÃ y. Vui lÃ²ng kiá»ƒm tra Canvas token.');
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
  };

  // Load selected course on mount
  useEffect(() => {
    const stored = getSelectedCourse();
    if (stored) {
      setSelectedCourse(stored);
    }
    // Always load indexed docs on mount (works offline)
    refreshIndexedData(stored?.id, 1);
  }, []);

  // Fetch remote files when course changes
  useEffect(() => {
    if (selectedCourse) {
      fetchRemoteFiles(selectedCourse.id);
      refreshIndexedData(selectedCourse.id, 1);
    }
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

    // Proceed to index via async job
    updateFileStatus(file.id, { status: 'indexing' });
    
    try {
      const asyncResp = await asyncIndexCanvasFile(filenameToIndex, selectedCourse?.id);
      const jobId = asyncResp.job_id;

      // Poll until job completes
      let jobResult = await getJob(jobId);
      while (!TERMINAL_STATUSES.includes(jobResult.status)) {
        await new Promise(resolve => setTimeout(resolve, 2000));
        jobResult = await getJob(jobId);
      }

      if (jobResult.status === 'SUCCEEDED' && jobResult.result) {
        const result = jobResult.result as {
          success?: boolean;
          already_indexed?: boolean;
          error?: string;
        };
        if (result.success) {
          if (result.already_indexed) {
            updateFileStatus(file.id, { status: 'indexed' });
          } else {
            updateFileStatus(file.id, { status: 'indexed' });
            // Refresh indexed docs to show updated status
            await refreshIndexedData(selectedCourse?.id, 1);
            // Dispatch event to notify DocumentRAGPanel to refresh topics
            window.dispatchEvent(new CustomEvent('canvas-topics-updated'));
          }
        } else {
          updateFileStatus(file.id, { 
            status: 'failed', 
            error: result.error || 'Index failed' 
          });
        }
      } else {
        updateFileStatus(file.id, { 
          status: 'failed', 
          error: jobResult.error_message || 'Index failed' 
        });
      }
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
      const result = await extractCanvasTopics(filename, 10);
      
      if (result.success) {
        setFileActionStates(prev => {
          const newMap = new Map(prev);
          newMap.delete(filename);
          return newMap;
        });
        await refreshIndexedData(selectedCourse?.id, 1);
        window.dispatchEvent(new CustomEvent('canvas-topics-updated'));
      } else {
        setFileActionStates(prev => new Map(prev).set(filename, 'failed'));
      }
    } catch (err) {
      if (err instanceof CanvasPermissionError) {
        alert('Không có quyền truy cập khóa học này. Vui lòng kiểm tra Canvas token.');
      }
      setFileActionStates(prev => new Map(prev).set(filename, 'failed'));
    }
  };

  const handleRemoveIndex = async (filename: string) => {
    if (!confirm(`Xóa index nội bộ cho "${filename}"?\nHành động này chỉ xóa dữ liệu vector và chủ đề trên hệ thống.\nFile trên Canvas LMS không bị ảnh hưởng.`)) {
      return;
    }
    
    try {
      const result = await removeCanvasFileIndex(filename);
      if (result.success) {
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
    
    if (!confirm(`Xóa index nội bộ cho "${file.display_name}"?\nHành động này chỉ xóa dữ liệu vector và chủ đề trên hệ thống.\nFile trên Canvas LMS không bị ảnh hưởng.`)) {
      return;
    }
    
    try {
      // Try with both original and sanitized name
      let result = await removeCanvasFileIndex(sanitizedName);
      if (!result.success) {
        result = await removeCanvasFileIndex(file.display_name);
      }
      
      if (result.success) {
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
        ['queued', 'downloading', 'hashing', 'indexing', 'extracting'].includes(s.status)
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
                              const actionState = fileActionStates.get(
                                indexedDoc?.filename || file.display_name.replace(/[,]/g, '')
                              );
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
                                          {isIndexed && indexedDoc && ` · ${indexedDoc.topic_count} topics`}
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
                                            disabled={isDownloading || ['downloading', 'indexing'].includes(state?.status || '')}
                                            title="Tải & Index"
                                          >
                                            <Database size={14} />
                                          </button>
                                        </>
                                      )}
                                      {/* Indexed: extract topics, edit topics, remove index */}
                                      {isIndexed && indexedDoc && (
                                        <>
                                          <button
                                            className="btn-action"
                                            onClick={() => handleExtractTopics(indexedDoc.filename)}
                                            disabled={actionState === 'extracting'}
                                            title="Trích xuất chủ đề"
                                          >
                                            <Sparkles size={14} />
                                          </button>
                                          <button
                                            className="btn-action"
                                            onClick={() => openEditTopicsModal(indexedDoc.filename)}
                                            title="Sửa chủ đề"
                                          >
                                            <Edit2 size={14} />
                                          </button>
                                          <button
                                            className="btn-action warning"
                                            onClick={() => handleRemoveIndexForRemoteFile(file)}
                                            title="Xóa index nội bộ (không ảnh hưởng Canvas)"
                                          >
                                            <Trash size={14} />
                                          </button>
                                        </>
                                      )}
                                      {/* Indexed but no doc found — just show remove */}
                                      {isIndexed && !indexedDoc && (
                                        <button
                                          className="btn-action warning"
                                          onClick={() => handleRemoveIndexForRemoteFile(file)}
                                          title="Xóa index nội bộ (không ảnh hưởng Canvas)"
                                        >
                                          <Trash size={14} />
                                        </button>
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
                    <div className="pagination">
                      <button
                        className="pagination-btn"
                        onClick={() => setRemoteCurrentPage(p => Math.max(1, p - 1))}
                        disabled={remoteCurrentPage === 1}
                      >
                        <ChevronLeft size={16} />
                      </button>
                      <div className="pagination-pages">
                        {Array.from({ length: totalPages }, (_, i) => i + 1).map(page => (
                          <button
                            key={page}
                            className={`pagination-page ${page === remoteCurrentPage ? 'active' : ''}`}
                            onClick={() => setRemoteCurrentPage(page)}
                          >
                            {page}
                          </button>
                        ))}
                      </div>
                      <button
                        className="pagination-btn"
                        onClick={() => setRemoteCurrentPage(p => Math.min(totalPages, p + 1))}
                        disabled={remoteCurrentPage === totalPages}
                      >
                        <ChevronRight size={16} />
                      </button>
                      <span className="pagination-info">
                        {remoteFiles.length > 0 
                          ? `${startIndex + 1}-${Math.min(startIndex + ITEMS_PER_PAGE, remoteFiles.length)} / ${remoteFiles.length}`
                          : '0 / 0'
                        }
                      </span>
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
              return (
                <>
                  <div className="files-list">
                    <table className="files-table">
                      <thead>
                        <tr>
                          <th>Tên file</th>
                          <th>Chunks</th>
                          <th>Topics</th>
                          <th>Thao tác</th>
                        </tr>
                      </thead>
                      <tbody>
                        {indexedDocs.length > 0 ? (
                          indexedDocs.map((doc) => {
                            const actionState = fileActionStates.get(doc.filename);
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
                            <td colSpan={4} className="empty-table-message">
                              Chưa có tài liệu nào được index.
                            </td>
                          </tr>
                        )}
                      </tbody>
                    </table>
                  </div>

                  {/* Pagination */}
                  {indexedTotalPages > 1 && (
                    <div className="pagination">
                      <button
                        className="pagination-btn"
                        onClick={() => loadIndexedDocs(selectedCourse?.id, indexedCurrentPage - 1)}
                        disabled={indexedCurrentPage <= 1}
                      >
                        <ChevronLeft size={16} />
                      </button>
                      <div className="pagination-pages">
                        {Array.from({ length: indexedTotalPages }, (_, i) => i + 1).map(page => (
                          <button
                            key={page}
                            className={`pagination-page ${page === indexedCurrentPage ? 'active' : ''}`}
                            onClick={() => loadIndexedDocs(selectedCourse?.id, page)}
                          >
                            {page}
                          </button>
                        ))}
                      </div>
                      <button
                        className="pagination-btn"
                        onClick={() => loadIndexedDocs(selectedCourse?.id, indexedCurrentPage + 1)}
                        disabled={indexedCurrentPage >= indexedTotalPages}
                      >
                        <ChevronRight size={16} />
                      </button>
                      <span className="pagination-info">
                        {`${(indexedCurrentPage - 1) * ITEMS_PER_PAGE + 1}-${Math.min(indexedCurrentPage * ITEMS_PER_PAGE, indexedTotal)} / ${indexedTotal}`}
                      </span>
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
