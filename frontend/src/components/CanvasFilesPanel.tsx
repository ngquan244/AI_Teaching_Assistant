import React, { useState, useEffect, useCallback } from 'react';
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
  Trash2,
  Edit2,
  X,
  Plus,
  Save,
  Trash,
  ChevronLeft,
  ChevronRight,
} from 'lucide-react';
import { canvasApi } from '../api/canvas';
import {
  downloadCanvasFile,
  indexCanvasFile,
  extractCanvasTopics,
  listCanvasFiles,
  listIndexedCanvasDocuments,
  getCanvasStats,
  getCanvasDocumentTopics,
  updateCanvasDocumentTopics,
  deleteCanvasFile,
  removeCanvasFileIndex,
  type CanvasFile as CanvasLocalFile,
  type CanvasIndexedDocument,
  type CanvasStats,
} from '../api/canvasRag';
import {
  isCanvasConfigured,
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
  hashing: 'Đang kiểm tra MD5...',
  saved: 'Đã lưu',
  duplicate: 'Đã có sẵn',
  failed: 'Thất bại',
  indexing: 'Đang index...',
  indexed: 'Đã index',
  extracting: 'Đang trích xuất...',
};

// Tab type for the panel
type PanelTab = 'remote' | 'local';

const CanvasFilesPanel: React.FC = () => {
  const [activeTab, setActiveTab] = useState<PanelTab>('remote');
  
  // Remote files state (from Canvas API)
  const [isModalOpen, setIsModalOpen] = useState(false);
  const [selectedCourse, setSelectedCourse] = useState<{
    id: number;
    name: string;
  } | null>(null);
  const [remoteFiles, setRemoteFiles] = useState<CanvasFile[]>([]);
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [downloadStates, setDownloadStates] = useState<
    Map<number, ExtendedDownloadState>
  >(new Map());
  const [isDownloading, setIsDownloading] = useState(false);

  // Local files state (downloaded files)
  const [localFiles, setLocalFiles] = useState<CanvasLocalFile[]>([]);
  const [indexedDocs, setIndexedDocs] = useState<CanvasIndexedDocument[]>([]);
  const [canvasStats, setCanvasStats] = useState<CanvasStats | null>(null);
  const [localLoading, setLocalLoading] = useState(false);
  const [localFileStates, setLocalFileStates] = useState<Map<string, ExtendedFileStatus>>(new Map());
  
  // Pagination state
  const [remoteCurrentPage, setRemoteCurrentPage] = useState(1);
  const [localCurrentPage, setLocalCurrentPage] = useState(1);
  const ITEMS_PER_PAGE = 5; // 5 files per page for testing (change to 10 for production)

  // Edit topics modal state
  const [showEditTopicsModal, setShowEditTopicsModal] = useState(false);
  const [editingFilename, setEditingFilename] = useState('');
  const [editingTopics, setEditingTopics] = useState<string[]>([]);
  const [newTopicInput, setNewTopicInput] = useState('');
  const [editingTopicIndex, setEditingTopicIndex] = useState<number | null>(null);
  const [editingTopicValue, setEditingTopicValue] = useState('');
  const [isSavingTopics, setIsSavingTopics] = useState(false);

  // Load selected course on mount
  useEffect(() => {
    const stored = getSelectedCourse();
    if (stored) {
      setSelectedCourse(stored);
    }
  }, []);

  // Fetch remote files when course changes
  useEffect(() => {
    if (selectedCourse) {
      fetchRemoteFiles(selectedCourse.id);
    }
  }, [selectedCourse]);

  // Load local files when switching to local tab
  useEffect(() => {
    if (activeTab === 'local') {
      loadLocalData();
    }
  }, [activeTab]);

  // Reset pagination when data changes
  useEffect(() => {
    setRemoteCurrentPage(1);
  }, [remoteFiles.length]);

  useEffect(() => {
    setLocalCurrentPage(1);
  }, [localFiles.length]);

  const fetchRemoteFiles = async (courseId: number) => {
    setLoading(true);
    setError(null);
    setRemoteFiles([]);
    setDownloadStates(new Map());

    try {
      // Fetch remote files and local data in parallel
      const [remoteResponse, localFilesRes, indexedRes] = await Promise.all([
        canvasApi.fetchCourseFiles(courseId),
        listCanvasFiles(),
        listIndexedCanvasDocuments(),
      ]);

      if (!remoteResponse.success) {
        setError(remoteResponse.error || 'Failed to fetch files');
        return;
      }

      setRemoteFiles(remoteResponse.files);
      
      // Update local data
      if (localFilesRes.success) {
        setLocalFiles(localFilesRes.files);
      }
      if (indexedRes.success) {
        setIndexedDocs(indexedRes.documents);
      }
      
      // Check status for each remote file
      const localFileSet = new Set(
        localFilesRes.success 
          ? localFilesRes.files.map(f => f.filename.toLowerCase().trim()) 
          : []
      );
      const indexedFileSet = new Set(
        indexedRes.success 
          ? indexedRes.documents.map(d => d.filename.toLowerCase().trim()) 
          : []
      );
      
      // Helper to sanitize filename for comparison (remove special chars)
      const sanitize = (name: string) => 
        name.toLowerCase().replace(/[,]/g, '').replace(/\s+/g, ' ').trim();
      
      // Set initial status for files that are already downloaded/indexed
      const newStates = new Map<number, ExtendedDownloadState>();
      remoteResponse.files.forEach((file: CanvasFile) => {
        const remoteNameSanitized = sanitize(file.display_name);
        
        // Check if file exists locally or indexed (with sanitized name matching)
        const isIndexed = [...indexedFileSet].some(indexedName => 
          sanitize(indexedName) === remoteNameSanitized ||
          remoteNameSanitized.includes(sanitize(indexedName.replace('.pdf', ''))) ||
          sanitize(indexedName).includes(remoteNameSanitized.replace('.pdf', ''))
        );
        const isDownloaded = [...localFileSet].some(localName =>
          sanitize(localName) === remoteNameSanitized ||
          remoteNameSanitized.includes(sanitize(localName.replace('.pdf', ''))) ||
          sanitize(localName).includes(remoteNameSanitized.replace('.pdf', ''))
        );
        
        if (isIndexed) {
          newStates.set(file.id, {
            fileId: file.id,
            filename: file.display_name,
            status: 'indexed',
          });
        } else if (isDownloaded) {
          newStates.set(file.id, {
            fileId: file.id,
            filename: file.display_name,
            status: 'saved',
          });
        }
      });
      
      if (newStates.size > 0) {
        setDownloadStates(newStates);
      }
    } catch (err) {
      setError('Network error. Please check your connection.');
    } finally {
      setLoading(false);
    }
  };

  const loadLocalData = async () => {
    setLocalLoading(true);
    try {
      const [filesRes, indexedRes, statsRes] = await Promise.all([
        listCanvasFiles(),
        listIndexedCanvasDocuments(),
        getCanvasStats(),
      ]);
      
      if (filesRes.success) {
        setLocalFiles(filesRes.files);
      }
      if (indexedRes.success) {
        setIndexedDocs(indexedRes.documents);
      }
      if (statsRes.success) {
        setCanvasStats(statsRes.stats);
      }
    } catch (err) {
      console.error('Error loading local data:', err);
    } finally {
      setLocalLoading(false);
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
      const isAlreadyIndexed = indexedDocs.some(doc => doc.filename === filenameToIndex);
      if (isAlreadyIndexed) {
        updateFileStatus(file.id, { 
          status: 'indexed',
          md5Hash: downloadResult.md5_hash,
        });
        return;
      }
    }

    // Proceed to index
    updateFileStatus(file.id, { status: 'indexing' });
    
    try {
      const indexResult = await indexCanvasFile(filenameToIndex);
      
      if (indexResult.success) {
        updateFileStatus(file.id, { status: 'indexed' });
        // Refresh local files list to show updated status
        await loadLocalData();
        // Dispatch event to notify DocumentRAGPanel to refresh topics
        window.dispatchEvent(new CustomEvent('canvas-topics-updated'));
      } else if (indexResult.already_indexed) {
        updateFileStatus(file.id, { status: 'indexed' });
      } else {
        updateFileStatus(file.id, { 
          status: 'failed', 
          error: indexResult.error || 'Index failed' 
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
    
    // Refresh local data
    loadLocalData();
  };

  // Local file actions
  const handleIndexLocalFile = async (filename: string) => {
    setLocalFileStates(prev => new Map(prev).set(filename, 'indexing'));
    
    try {
      const result = await indexCanvasFile(filename);
      
      if (result.success) {
        setLocalFileStates(prev => new Map(prev).set(filename, 'indexed'));
        await loadLocalData();
        // Dispatch event to notify DocumentRAGPanel to refresh topics
        window.dispatchEvent(new CustomEvent('canvas-topics-updated'));
      } else {
        setLocalFileStates(prev => new Map(prev).set(filename, 'failed'));
      }
    } catch (err) {
      setLocalFileStates(prev => new Map(prev).set(filename, 'failed'));
    }
  };

  const handleExtractTopics = async (filename: string) => {
    setLocalFileStates(prev => new Map(prev).set(filename, 'extracting'));
    
    try {
      const result = await extractCanvasTopics(filename, 10);
      
      if (result.success) {
        setLocalFileStates(prev => {
          const newMap = new Map(prev);
          newMap.delete(filename);
          return newMap;
        });
        await loadLocalData();
        // Dispatch event to notify DocumentRAGPanel to refresh topics
        window.dispatchEvent(new CustomEvent('canvas-topics-updated'));
      } else {
        setLocalFileStates(prev => new Map(prev).set(filename, 'failed'));
      }
    } catch (err) {
      setLocalFileStates(prev => new Map(prev).set(filename, 'failed'));
    }
  };

  const handleRemoveIndex = async (filename: string) => {
    if (!confirm(`Xóa index cho "${filename}"? File sẽ được giữ lại nhưng cần index lại để sử dụng.`)) {
      return;
    }
    
    try {
      const result = await removeCanvasFileIndex(filename);
      if (result.success) {
        await loadLocalData();
        // Dispatch event to notify DocumentRAGPanel to refresh topics
        window.dispatchEvent(new CustomEvent('canvas-topics-updated'));
      }
    } catch (err) {
      console.error('Error removing index:', err);
    }
  };

  // Remove index for remote file (from Canvas tab)
  const handleRemoveIndexForRemoteFile = async (file: CanvasFile) => {
    // Find the local filename (sanitized)
    const sanitizedName = file.display_name.replace(/[,]/g, '');
    
    if (!confirm(`Xóa index cho "${file.display_name}"? File sẽ được giữ lại nhưng cần index lại để sử dụng.`)) {
      return;
    }
    
    try {
      // Try with both original and sanitized name
      let result = await removeCanvasFileIndex(sanitizedName);
      if (!result.success) {
        result = await removeCanvasFileIndex(file.display_name);
      }
      
      if (result.success) {
        // Update status to 'saved' (downloaded but not indexed)
        setDownloadStates(prev => {
          const newMap = new Map(prev);
          newMap.set(file.id, {
            fileId: file.id,
            filename: file.display_name,
            status: 'saved',
          });
          return newMap;
        });
        await loadLocalData();
        // Dispatch event to notify DocumentRAGPanel to refresh topics
        window.dispatchEvent(new CustomEvent('canvas-topics-updated'));
      }
    } catch (err) {
      console.error('Error removing index:', err);
    }
  };

  const handleDeleteLocalFile = async (filename: string) => {
    if (!confirm(`Xóa file "${filename}"? Hành động này không thể hoàn tác.`)) {
      return;
    }
    
    try {
      const result = await deleteCanvasFile(filename);
      if (result.success) {
        await loadLocalData();
      }
    } catch (err) {
      console.error('Error deleting file:', err);
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
        await loadLocalData();
      } else {
        alert('Không thể lưu chủ đề. Vui lòng thử lại.');
      }
    } catch (error) {
      console.error('Error saving topics:', error);
      alert('Lỗi khi lưu chủ đề.');
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

  const isConfigured = isCanvasConfigured();

  if (!isConfigured) {
    return (
      <div className="canvas-panel">
        <h2>
          <FolderOpen size={24} />
          Canvas Files
        </h2>
        <div className="canvas-not-configured">
          <AlertCircle size={48} />
          <h3>Canvas Not Configured</h3>
          <p>Please add your Canvas access token in Settings first.</p>
        </div>
      </div>
    );
  }

  return (
    <div className="canvas-panel">
      <h2>
        <FolderOpen size={24} />
        Canvas Files
      </h2>

      {/* Tab Switcher */}
      <div className="canvas-tabs">
        <button
          className={`tab-btn ${activeTab === 'remote' ? 'active' : ''}`}
          onClick={() => setActiveTab('remote')}
        >
          <Download size={16} />
          Từ Canvas
        </button>
        <button
          className={`tab-btn ${activeTab === 'local' ? 'active' : ''}`}
          onClick={() => setActiveTab('local')}
        >
          <Database size={16} />
          Đã tải ({localFiles.length})
        </button>
      </div>

      {/* Remote Files Tab */}
      {activeTab === 'remote' && (
        <>
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
          {selectedCourse && (
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
                        <span className="summary-item saved">
                          <CheckCircle size={14} /> {summary.saved} saved
                        </span>
                        <span className="summary-item indexed">
                          <Database size={14} /> {summary.indexed} indexed
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
                              const isIndexed = state?.status === 'indexed';
                              const isSaved = state?.status === 'saved';
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
                                    {state ? (
                                      <div className={`file-status ${state.status}`}>
                                        <StatusIcon status={state.status} />
                                        <span>{statusLabels[state.status]}</span>
                                      </div>
                                    ) : (
                                      <span className="file-status idle">—</span>
                                    )}
                                  </td>
                                  <td>
                                    <div className="action-buttons">
                                      {/* Download only button */}
                                      {!isIndexed && !isSaved && (
                                        <button
                                          className="btn-action"
                                          onClick={() => downloadSingleFile(file)}
                                          disabled={isDownloading || ['downloading', 'indexing'].includes(state?.status || '')}
                                          title="Chỉ tải"
                                        >
                                          <Download size={14} />
                                        </button>
                                      )}
                                      {/* Download & Index button (or just Index if already saved) */}
                                      {!isIndexed && (
                                        <button
                                          className="btn-action btn-primary-action"
                                          onClick={() => downloadAndIndexFile(file)}
                                          disabled={isDownloading || ['downloading', 'indexing'].includes(state?.status || '')}
                                          title={isSaved ? "Index" : "Tải & Index"}
                                        >
                                          <Database size={14} />
                                        </button>
                                      )}
                                      {/* Remove index button (when indexed) */}
                                      {isIndexed && (
                                        <button
                                          className="btn-action warning"
                                          onClick={() => handleRemoveIndexForRemoteFile(file)}
                                          title="Xóa index"
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
                    
                    {/* Pagination - Always show */}
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
        </>
      )}

      {/* Local Files Tab */}
      {activeTab === 'local' && (
        <div className="canvas-section">
          {/* Stats */}
          {canvasStats && (
            <div className="canvas-stats">
              <div className="stat-item">
                <span className="stat-value">{canvasStats.total_documents}</span>
                <span className="stat-label">Tài liệu</span>
              </div>
              <div className="stat-item">
                <span className="stat-value">{canvasStats.total_chunks}</span>
                <span className="stat-label">Chunks</span>
              </div>
            </div>
          )}

          <div className="section-header">
            <h3>File đã tải từ Canvas</h3>
            <button
              className="btn-secondary btn-sm"
              onClick={loadLocalData}
              disabled={localLoading}
            >
              <RefreshCw size={16} className={localLoading ? 'spin' : ''} />
              Refresh
            </button>
          </div>

          {localLoading && (
            <div className="loading-center">
              <Loader2 className="spin" size={32} />
            </div>
          )}

          {!localLoading && (() => {
            const totalPages = Math.max(1, Math.ceil(localFiles.length / ITEMS_PER_PAGE));
            const startIndex = (localCurrentPage - 1) * ITEMS_PER_PAGE;
            const paginatedFiles = localFiles.slice(startIndex, startIndex + ITEMS_PER_PAGE);
            
            return (
              <>
                <div className="files-list">
                  <table className="files-table">
                    <thead>
                      <tr>
                        <th>Tên file</th>
                        <th>Kích thước</th>
                        <th>Trạng thái</th>
                        <th>Topics</th>
                        <th>Thao tác</th>
                      </tr>
                    </thead>
                    <tbody>
                      {paginatedFiles.length > 0 ? (
                        paginatedFiles.map((file) => {
                          const indexed = indexedDocs.find(d => d.filename === file.filename);
                          const fileState = localFileStates.get(file.filename);
                          
                          return (
                            <tr key={file.filename}>
                              <td>
                                <div className="file-name">
                                  <FileText size={16} />
                                  <span>{file.filename}</span>
                                </div>
                              </td>
                              <td>{formatFileSize(file.size)}</td>
                              <td>
                                {fileState ? (
                                  <div className={`file-status ${fileState}`}>
                                    <StatusIcon status={fileState} />
                                    <span>{statusLabels[fileState]}</span>
                                  </div>
                                ) : indexed ? (
                                  <div className="file-status indexed">
                                    <Database size={16} />
                                    <span>Indexed</span>
                                  </div>
                                ) : (
                                  <span className="file-status idle">Chưa index</span>
                                )}
                              </td>
                              <td>
                                {indexed ? (
                                  <span className="topic-count">
                                    {indexed.topic_count} topics
                                  </span>
                                ) : (
                                  <span className="topic-count empty">—</span>
                                )}
                              </td>
                              <td>
                                <div className="action-buttons">
                                  {!indexed && (
                                    <button
                                      className="btn-action btn-primary-action"
                                      onClick={() => handleIndexLocalFile(file.filename)}
                                      disabled={fileState === 'indexing'}
                                      title="Index file"
                                    >
                                      <Database size={14} />
                                    </button>
                                  )}
                                  {indexed && (
                                    <>
                                      <button
                                        className="btn-action"
                                        onClick={() => handleExtractTopics(file.filename)}
                                        disabled={fileState === 'extracting'}
                                        title="Trích xuất chủ đề"
                                      >
                                        <BookOpen size={14} />
                                      </button>
                                      <button
                                        className="btn-action"
                                        onClick={() => openEditTopicsModal(file.filename)}
                                        title="Sửa chủ đề"
                                      >
                                        <Edit2 size={14} />
                                      </button>
                                      <button
                                        className="btn-action warning"
                                        onClick={() => handleRemoveIndex(file.filename)}
                                        title="Xóa index (giữ file)"
                                      >
                                        <Trash size={14} />
                                      </button>
                                    </>
                                  )}
                                  <button
                                    className="btn-action danger"
                                    onClick={() => handleDeleteLocalFile(file.filename)}
                                    title="Xóa file và index"
                                  >
                                    <Trash2 size={14} />
                                  </button>
                                </div>
                              </td>
                            </tr>
                          );
                        })
                      ) : (
                        <tr>
                          <td colSpan={5} className="empty-table-message">
                            Chưa có file nào được tải từ Canvas.
                          </td>
                        </tr>
                      )}
                    </tbody>
                  </table>
                </div>
                
                {/* Pagination - Always show */}
                <div className="pagination">
                  <button
                    className="pagination-btn"
                    onClick={() => setLocalCurrentPage(p => Math.max(1, p - 1))}
                    disabled={localCurrentPage === 1}
                  >
                    <ChevronLeft size={16} />
                  </button>
                  <div className="pagination-pages">
                    {Array.from({ length: totalPages }, (_, i) => i + 1).map(page => (
                      <button
                        key={page}
                        className={`pagination-page ${page === localCurrentPage ? 'active' : ''}`}
                        onClick={() => setLocalCurrentPage(page)}
                      >
                        {page}
                      </button>
                    ))}
                  </div>
                  <button
                    className="pagination-btn"
                    onClick={() => setLocalCurrentPage(p => Math.min(totalPages, p + 1))}
                    disabled={localCurrentPage === totalPages}
                  >
                    <ChevronRight size={16} />
                  </button>
                  <span className="pagination-info">
                    {localFiles.length > 0 
                      ? `${startIndex + 1}-${Math.min(startIndex + ITEMS_PER_PAGE, localFiles.length)} / ${localFiles.length}`
                      : '0 / 0'
                    }
                  </span>
                </div>
              </>
            );
          })()}
        </div>
      )}

      {/* Course Selection Modal */}
      <CanvasCourseModal
        isOpen={isModalOpen}
        onClose={() => setIsModalOpen(false)}
        onCourseSelected={handleCourseSelected}
      />

      {/* Edit Topics Modal */}
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
