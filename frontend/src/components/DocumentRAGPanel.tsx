import React, { useState, useEffect, useRef, useMemo } from 'react';
import {
  FileText,
  Upload,
  Database,
  Trash2,
  RefreshCw,
  CheckCircle,
  AlertCircle,
  Loader2,
  ChevronDown,
  ChevronUp,
  FileIcon,
  Info,
  BookOpen,
  HelpCircle,
  Check,
  X,
  Edit2,
  Download,
  Save,
  Zap,
  Plus,
  Pencil,
  Clock,
  FileUp,
  XCircle,
  FolderOpen,
  Rocket,
  Library,
  Sparkles,
} from 'lucide-react';
import PanelHelpButton from './PanelHelpButton';

/* ---------- tiny helper: random stars for background ---------- */
const generateRAGStars = (count: number) =>
  Array.from({ length: count }, (_, i) => ({
    id: i,
    top: `${Math.random() * 100}%`,
    left: `${Math.random() * 100}%`,
    duration: `${3 + Math.random() * 4}s`,
    delay: `${Math.random() * 5}s`,
    size: `${1.5 + Math.random() * 1.5}px`,
  }));
import {
  getRAGStats,
  resetRAGIndex,
  checkLLMStatus,
  listUploadedFiles,
  exportQuizToQTI,
  getDocumentTopics,
  updateDocumentTopics,
  listIndexedDocuments,
  getLLMProviderInfo,
  asyncUploadAndIndex,
  asyncBuildIndex,
  asyncGenerateQuiz,
  asyncExtractTopicsForDocument,
  removeDocumentIndex,
  deleteUploadedFile,
  type GenerateQuizResponse,
  type RAGIndexStats,
  type RAGUploadedFile,
  type LLMStatus,
  type QuizQuestion,
  type TopicSuggestion,
  type LLMProviderInfo,
} from '../api/documentRag';
import { getJob, TERMINAL_STATUSES, type JobOut } from '../api/jobs';
import { useAsyncJob } from '../hooks/useAsyncJob';
import { useConfirm } from '../context/ConfirmContext';
import JobProgressModal from './JobProgressModal';
import {
  listIndexedCanvasDocuments,
  getCanvasDocumentTopics,
  updateCanvasDocumentTopics,
  asyncCanvasGenerateQuiz,
  getPublicConfig,
  type PublicConfig,
} from '../api/canvasRag';
import CanvasImportModal from './CanvasImportModal';
import { savedQuizApi } from '../api/savedQuiz';

// Indexed document info
interface IndexedDocument {
  filename: string;
  original_filename: string;
  topic_count: number;
  indexed_at: string;
  course_id?: number;
  course_name?: string;
}

// Topic source type
type TopicSource = 'upload' | 'canvas';



// Multi-file upload status
type FileUploadStatus = 'waiting' | 'uploading' | 'success' | 'error' | 'already_indexed';

interface UploadFileItem {
  file: File;
  status: FileUploadStatus;
  message?: string;
  details?: {
    filename?: string;
    pages_loaded?: number;
    chunks_added?: number;
  };
}



interface DocumentRAGPanelProps {
  /** Callback to deploy generated quiz to QuizBuilder tab */
  onDeployToCanvas?: (questions: QuizQuestion[]) => void;
}

const DocumentRAGPanel: React.FC<DocumentRAGPanelProps> = ({ onDeployToCanvas }) => {
  const confirmDialog = useConfirm();
  // Decorative stars
  const ragStars = useMemo(() => generateRAGStars(24), []);

  // Async job hook for quiz generation
  const quizJob = useAsyncJob({ storageKey: 'quizJob' });

  // State
  const [selectedFile, setSelectedFile] = useState<File | null>(null);
  const [selectedFiles, setSelectedFiles] = useState<UploadFileItem[]>([]);
  const [isProcessingQueue, setIsProcessingQueue] = useState(false);

  
  // Quiz states
  const [quizTopic, setQuizTopic] = useState('');
  const [numQuestions, setNumQuestions] = useState(5);
  const [quizDifficulty, setQuizDifficulty] = useState<'easy' | 'medium' | 'hard'>('medium');
  const [quizLanguage, setQuizLanguage] = useState<'vi' | 'en'>('vi');

  // V2 — course-shared domain knowledge
  const [publicConfig, setPublicConfig] = useState<PublicConfig | null>(null);
  const [includeCourseDomain, setIncludeCourseDomain] = useState(true);
  // Stored as percentage (0–60) for the slider; converted to ratio in the request.
  const [domainQuotaPct, setDomainQuotaPct] = useState(30);

  useEffect(() => {
    let alive = true;
    getPublicConfig()
      .then((cfg) => {
        if (!alive) return;
        setPublicConfig(cfg);
        const pct = Math.round((cfg.default_domain_quota_ratio ?? 0.3) * 100);
        setDomainQuotaPct(Math.min(60, Math.max(0, pct)));
      })
      .catch((err) => {
        console.warn('Failed to load public config:', err);
      });
    return () => {
      alive = false;
    };
  }, []);
  const [generatedQuiz, setGeneratedQuiz] = useState<QuizQuestion[]>([]);
  const [isGeneratingQuiz, setIsGeneratingQuiz] = useState(false);
  const [quizError, setQuizError] = useState<string | null>(null);
  const [quizMessage, setQuizMessage] = useState<string | null>(null);
  const [editingQuestionIndex, setEditingQuestionIndex] = useState<number | null>(null);
  const [editingQuestion, setEditingQuestion] = useState<QuizQuestion | null>(null);
  const [isExporting, setIsExporting] = useState(false);
  
  // Save to library states
  const [isSavingToLibrary, setIsSavingToLibrary] = useState(false);
  const [saveLibrarySuccess, setSaveLibrarySuccess] = useState(false);

  // Save-quiz modal (V2 — pop-up trước khi lưu vào Kho Đề)
  const [showSaveQuizModal, setShowSaveQuizModal] = useState(false);
  const [saveQuizTitle, setSaveQuizTitle] = useState('');
  const [saveQuizDescription, setSaveQuizDescription] = useState('');
  const [saveQuizTagsInput, setSaveQuizTagsInput] = useState('');
  const [saveQuizError, setSaveQuizError] = useState<string | null>(null);
  
  // Document and Topic selection states
  const [indexedDocuments, setIndexedDocuments] = useState<IndexedDocument[]>([]);
  // Lookup map across ALL indexed documents (not paginated) so per-row status
  // (Đã index / topic_count) is correct even when the uploaded-files list and
  // the indexed-documents list use different pagination windows.
  const [indexedDocsMap, setIndexedDocsMap] = useState<Map<string, IndexedDocument>>(new Map());
  // True while we are (re)building the indexed-filename map. Used by the
  // Files-đã-upload table to render "Đang tải…" instead of an empty pill.
  const [indexedDocsMapLoading, setIndexedDocsMapLoading] = useState(true);
  const [selectedDocuments, setSelectedDocuments] = useState<string[]>([]);
  const [topicsCache, setTopicsCache] = useState<Record<string, TopicSuggestion[]>>({});
  const [topicsByDocument, setTopicsByDocument] = useState<Record<string, TopicSuggestion[]>>({});
  const [topicLoadingState, setTopicLoadingState] = useState<Record<string, boolean>>({});
  const [topicErrorState, setTopicErrorState] = useState<Record<string, string | null>>({});
  const [selectedTopics, setSelectedTopics] = useState<{topic: string, documentFilename: string}[]>([]);
  
  // Topic selector modal states
  const [showTopicModal, setShowTopicModal] = useState(false);
  const [tempSelectedDocuments, setTempSelectedDocuments] = useState<string[]>([]);
  const [tempSelectedTopics, setTempSelectedTopics] = useState<{topic: string, documentFilename: string}[]>([]);
  const [tempTopicsByDocument, setTempTopicsByDocument] = useState<Record<string, TopicSuggestion[]>>({});
  
  // Topic source state (upload or canvas)
  const [topicSource, setTopicSource] = useState<TopicSource>('upload');
  const [canvasIndexedDocuments, setCanvasIndexedDocuments] = useState<IndexedDocument[]>([]);
  const [canvasTopicsCache, setCanvasTopicsCache] = useState<Record<string, TopicSuggestion[]>>({});
  
  // Course name resolution for Canvas documents
  const [courseNameMap, setCourseNameMap] = useState<Record<number, string>>({});
  const [collapsedCourses, setCollapsedCourses] = useState<Set<number>>(new Set());

  // Edit topics modal states
  const [showEditTopicsModal, setShowEditTopicsModal] = useState(false);
  const [editingDocumentFilename, setEditingDocumentFilename] = useState<string>('');
  const [editingTopics, setEditingTopics] = useState<string[]>([]);
  const [newTopicInput, setNewTopicInput] = useState('');
  const [editingTopicIndex, setEditingTopicIndex] = useState<number | null>(null);
  const [editingTopicValue, setEditingTopicValue] = useState('');
  const [isSavingTopics, setIsSavingTopics] = useState(false);
  
  // Quiz modal state
  const [showQuizModal, setShowQuizModal] = useState(false);
  
  // Canvas Import Modal state
  const [showCanvasImportModal, setShowCanvasImportModal] = useState(false);
  const [qtiZipBlob, setQtiZipBlob] = useState<Blob | null>(null);
  
  // Loading states
  const [isUploading, setIsUploading] = useState(false);

  const [isResetting, setIsResetting] = useState(false);
  
  // Status states
  const [indexStats, setIndexStats] = useState<RAGIndexStats | null>(null);
  const [llmStatus, setLlmStatus] = useState<LLMStatus | null>(null);
  const [uploadedFiles, setUploadedFiles] = useState<RAGUploadedFile[]>([]);
  const [uploadedPage, setUploadedPage] = useState(1);
  const [uploadedPages, setUploadedPages] = useState(1);
  const [uploadedTotal, setUploadedTotal] = useState(0);
  const [indexedPage, setIndexedPage] = useState(1);
  const [indexedPages, setIndexedPages] = useState(1);
  const [indexedTotal, setIndexedTotal] = useState(0);
  
  // Messages
  const [uploadMessage, setUploadMessage] = useState<{ type: 'success' | 'error' | 'info'; text: string } | null>(null);

  

  // LLM Provider states
  const [llmProviderInfo, setLlmProviderInfo] = useState<LLMProviderInfo | null>(null);
  
  const fileInputRef = useRef<HTMLInputElement>(null);
  const getTopicStateKey = (source: TopicSource, filename: string) => `${source}:${filename}`;

  // ── Selection-key helpers ──────────────────────────────────────────────────
  // Canvas documents are unique per (user, file_hash, course_id) in the DB,
  // but multiple courses can have a file with the same filename/hash.  We
  // therefore use a composite key that embeds the course_id so that two docs
  // with identical filenames in different courses are never conflated.
  //
  //  Canvas doc  →  "courseId::filename"  (e.g. "42::lecture1.pdf")
  //  Upload doc  →  "filename"            (course_id is undefined)
  const getDocSelectionKey = (doc: IndexedDocument): string => {
    if (doc.course_id != null) {
      return `${doc.course_id}::${doc.filename}`;
    }
    return doc.filename;
  };

  // Extract the plain filename from a selection key.
  const getFilenameFromKey = (key: string): string => {
    const sep = key.indexOf('::');
    return sep === -1 ? key : key.slice(sep + 2);
  };

  // Extract course_id from a selection key.  Returns undefined for upload docs.
  const getCourseIdFromKey = (key: string): number | undefined => {
    const sep = key.indexOf('::');
    if (sep === -1) return undefined;
    const id = parseInt(key.slice(0, sep), 10);
    return isNaN(id) ? undefined : id;
  };

  // Load initial data
  useEffect(() => {
    loadIndexStats();
    loadLLMStatus();
    loadUploadedFiles();
    loadIndexedDocuments();
    loadCanvasIndexedDocuments();
    loadLLMProviderInfo();
  }, []);

  // Handle quiz job completion — extract result into component state
  useEffect(() => {
    const job = quizJob.job;
    if (!job) return;

    if (job.status === 'SUCCEEDED' && job.result) {
      const r = job.result as unknown as GenerateQuizResponse;
      if (r.success && r.questions && r.questions.length > 0) {
        setGeneratedQuiz(r.questions);
        setQuizError(null);
        setQuizMessage(r.partial ? (r.message || null) : null);
        setShowQuizModal(true);
      } else {
        setQuizMessage(null);
        setQuizError(r.error || r.message || 'Không thể tạo quiz. Hãy thử lại với chủ đề khác.');
      }
      setIsGeneratingQuiz(false);
      quizJob.reset();
    } else if (job.status === 'FAILED') {
      setQuizMessage(null);
      setQuizError(job.error_message || 'Lỗi khi tạo quiz.');
      setIsGeneratingQuiz(false);
      quizJob.reset();
    } else if (job.status === 'CANCELED') {
      setQuizMessage(null);
      setIsGeneratingQuiz(false);
      quizJob.reset();
    }
  }, [quizJob.job?.status]);

  // Listen for canvas topics updates from CanvasFilesPanel
  useEffect(() => {
    const handleCanvasTopicsUpdated = () => {
      loadCanvasIndexedDocuments();
      // Clear canvas topics cache to force reload
      setCanvasTopicsCache({});
      setTopicErrorState(prev => {
        const next = { ...prev };
        Object.keys(next).forEach((key) => {
          if (key.startsWith('canvas:')) delete next[key];
        });
        return next;
      });
    };

    window.addEventListener('canvas-topics-updated', handleCanvasTopicsUpdated);
    return () => {
      window.removeEventListener('canvas-topics-updated', handleCanvasTopicsUpdated);
    };
  }, []);

  // Load Canvas indexed documents
  const loadCanvasIndexedDocuments = async () => {
    // Always try to load - don't require Canvas configuration
    // since documents may already be indexed locally
    try {
      const response = await listIndexedCanvasDocuments(undefined, 1, 100);
      if (response.success && response.documents) {
        const docs: IndexedDocument[] = response.documents.map(d => ({
          filename: d.filename,
          original_filename: d.original_filename || d.filename,
          topic_count: d.topic_count,
          indexed_at: d.indexed_at,
          course_id: d.course_id,
          course_name: d.course_name,
        }));
        setCanvasIndexedDocuments(docs);
        // Build course name map from the response
        const map: Record<number, string> = {};
        for (const d of response.documents) {
          if (d.course_id != null && d.course_name) {
            map[d.course_id] = d.course_name;
          }
        }
        setCourseNameMap(prev => ({ ...prev, ...map }));
      }
    } catch (error) {
      console.error('Error loading Canvas indexed documents:', error);
    }
  };

  // Load LLM Provider info
  const loadLLMProviderInfo = async () => {
    try {
      const info = await getLLMProviderInfo();
      setLlmProviderInfo(info);
    } catch (error) {
      console.error('Error loading LLM provider info:', error);
    }
  };

  // Load indexed documents with topics
  const loadIndexedDocuments = async (page?: number) => {
    try {
      const p = page ?? indexedPage;
      const response = await listIndexedDocuments(p);
      if (response.success && response.documents) {
        setIndexedDocuments(response.documents);
        setIndexedPage(response.page);
        setIndexedPages(response.pages);
        setIndexedTotal(response.total);
      }
      // Always refresh the full lookup map so per-row badges stay accurate.
      void loadIndexedFilenameMap();
    } catch (error) {
      console.error('Error loading indexed documents:', error);
    }
  };

  // Build a Map<filename, IndexedDocument> over the entire indexed corpus.
  // Used by the Files-đã-upload table to render per-row index/topic status.
  // The backend caps page_size at 100, so we paginate to cover all docs.
  const loadIndexedFilenameMap = async () => {
    setIndexedDocsMapLoading(true);
    try {
      const map = new Map<string, IndexedDocument>();
      const PAGE_SIZE = 100;
      let page = 1;
      // Hard safety cap to avoid infinite loops if backend misbehaves.
      const MAX_PAGES = 50;
      while (page <= MAX_PAGES) {
        const response = await listIndexedDocuments(page, PAGE_SIZE);
        if (!response.success || !response.documents) break;
        for (const doc of response.documents) {
          map.set(doc.filename, doc as IndexedDocument);
        }
        const totalPages = response.pages || 1;
        if (page >= totalPages) break;
        page += 1;
      }
      setIndexedDocsMap(map);
    } catch (error) {
      console.error('Error loading indexed filename map:', error);
    } finally {
      setIndexedDocsMapLoading(false);
    }
  };

  const loadIndexStats = async () => {
    try {
      const response = await getRAGStats();
      if (response.success) {
        setIndexStats(response.stats);
      }
    } catch (error) {
      console.error('Error loading stats:', error);
    }
  };

  const loadLLMStatus = async () => {
    try {
      const status = await checkLLMStatus();
      setLlmStatus(status);
    } catch (error) {
      console.error('Error checking LLM status:', error);
      setLlmStatus({
        connected: false,
        message: 'Không thể kết nối đến LLM provider',
        error: String(error),
      });
    }
  };

  const loadUploadedFiles = async (page?: number) => {
    try {
      const p = page ?? uploadedPage;
      const response = await listUploadedFiles(p, 5);
      if (response.success) {
        setUploadedFiles(response.files);
        setUploadedPage(response.page);
        setUploadedPages(response.pages);
        setUploadedTotal(response.total);
      }
    } catch (error) {
      console.error('Error loading files:', error);
    }
  };

  // Clear all selected topics
  const clearSelectedTopics = () => {
    setSelectedTopics([]);
    setSelectedDocuments([]);
    setTopicsByDocument({});
    setQuizTopic('');
  };

  // Modal handlers
  const openTopicModal = () => {
    // Copy current selections to temp states
    setTempSelectedDocuments([...selectedDocuments]);
    setTempSelectedTopics([...selectedTopics]);
    setTempTopicsByDocument({...topicsByDocument});
    setShowTopicModal(true);
  };

  const closeTopicModal = () => {
    setShowTopicModal(false);
    // Discard temp changes
    setTempSelectedDocuments([]);
    setTempSelectedTopics([]);
    setTempTopicsByDocument({});
  };

  const saveTopicSelections = () => {
    // Apply temp selections to main states
    setSelectedDocuments([...tempSelectedDocuments]);
    setSelectedTopics([...tempSelectedTopics]);
    setTopicsByDocument({...tempTopicsByDocument});
    setShowTopicModal(false);
  };

  // Modal - Toggle document selection.
  // Takes the full document object so we can build a composite selection key
  // that is globally unique even when the same file (same filename/hash)
  // exists in multiple Canvas courses.
  const toggleDocumentInModal = async (doc: IndexedDocument) => {
    const selectionKey = getDocSelectionKey(doc);   // e.g. "42::lecture1.pdf"
    const filename = doc.filename;                   // plain filename for API/cache
    const isCurrentlySelected = tempSelectedDocuments.includes(selectionKey);
    const stateKey = getTopicStateKey(topicSource, filename);

    // Block cross-course selection: if a doc from a different Canvas course is
    // already in the selection, reject the attempt with a clear message rather
    // than silently letting a false-positive slip through.
    if (!isCurrentlySelected && topicSource === 'canvas' && tempSelectedDocuments.length > 0) {
      const alreadySelectedCourseId = getCourseIdFromKey(tempSelectedDocuments[0]);
      if (alreadySelectedCourseId != null && doc.course_id !== alreadySelectedCourseId) {
        setTopicErrorState(prev => ({
          ...prev,
          [stateKey]: 'Vui lòng chỉ chọn tài liệu trong cùng một khoá học.',
        }));
        return;
      }
    }
    
    if (isCurrentlySelected) {
      // Remove document and its selected topics (compare by composite key)
      setTempSelectedDocuments(prev => prev.filter(k => k !== selectionKey));
      setTempSelectedTopics(st => st.filter(t => t.documentFilename !== selectionKey));
      setTempTopicsByDocument(prev => {
        const updated = { ...prev };
        delete updated[selectionKey];
        return updated;
      });
    } else {
      // Add document (store composite key)
      setTempSelectedDocuments(prev => [...prev, selectionKey]);
      
      // Auto-load topics for this document based on source.
      // Topic caches (canvasTopicsCache / topicsCache) continue to use the plain
      // filename as the key — they are not affected by the selection key change.
      const cache = topicSource === 'canvas' ? canvasTopicsCache : topicsCache;
      
      if (!cache[filename]) {
        setTopicLoadingState(prev => ({ ...prev, [stateKey]: true }));
        setTopicErrorState(prev => ({ ...prev, [stateKey]: null }));
        try {
          // Use appropriate API based on source
          let response;
          if (topicSource === 'canvas') {
            // course_id is already in the doc object — no extra lookup needed
            const canvasCourseId = doc.course_id;
            if (!canvasCourseId) {
              setTopicErrorState(prev => ({
                ...prev,
                [stateKey]: 'Khong xac dinh duoc khoa hoc cho tai lieu nay.',
              }));
              setTopicLoadingState(prev => ({ ...prev, [stateKey]: false }));
              return;
            }
            response = await getCanvasDocumentTopics(filename, canvasCourseId);
          } else {
            response = await getDocumentTopics(filename);
          }
          
          if (response.success) {
            const topicNames = response.topics || [];
            const topics: TopicSuggestion[] = topicNames.map((name, idx) => ({
              name,
              relevance_score: 1 - (idx * 0.05),
              description: ''
            }));
            
            // Update plain-filename-keyed caches (unchanged)
            if (topicSource === 'canvas') {
              setCanvasTopicsCache(prev => ({ ...prev, [filename]: topics }));
            } else {
              setTopicsCache(prev => ({ ...prev, [filename]: topics }));
            }
            // tempTopicsByDocument is keyed by composite selectionKey
            setTempTopicsByDocument(prev => ({ ...prev, [selectionKey]: topics }));
            if (topics.length === 0) {
              setTopicErrorState(prev => ({ ...prev, [stateKey]: 'Tai lieu nay chua co chu de nao.' }));
            }
          } else {
            setTopicErrorState(prev => ({ ...prev, [stateKey]: 'Khong the tai chu de cho tai lieu nay.' }));
          }
        } catch (error) {
          console.error('Error loading topics for document:', error);
          setTopicErrorState(prev => ({ ...prev, [stateKey]: 'Khong the tai chu de cho tai lieu nay.' }));
        } finally {
          setTopicLoadingState(prev => ({ ...prev, [stateKey]: false }));
        }
      } else {
        setTopicErrorState(prev => ({ ...prev, [stateKey]: cache[filename].length === 0 ? 'Tai lieu nay chua co chu de nao.' : null }));
        // tempTopicsByDocument is keyed by composite selectionKey
        setTempTopicsByDocument(prev => ({ ...prev, [selectionKey]: cache[filename] }));
      }
    }
  };

  // Modal - Toggle topic selection
  const toggleTopicInModal = (topic: string, documentFilename: string) => {
    setTempSelectedTopics(prev => {
      const exists = prev.find(t => t.topic === topic && t.documentFilename === documentFilename);
      if (exists) {
        return prev.filter(t => !(t.topic === topic && t.documentFilename === documentFilename));
      } else {
        return [...prev, { topic, documentFilename }];
      }
    });
  };

  // Modal - Check if topic is selected
  const isTopicSelectedInModal = (topic: string, documentFilename: string) => {
    return tempSelectedTopics.some(t => t.topic === topic && t.documentFilename === documentFilename);
  };

  // Modal - Select all topics from a document
  const selectAllTopicsInModal = (docFilename: string) => {
    const docTopics = tempTopicsByDocument[docFilename] || [];
    const newSelections = docTopics
      .filter(topic => !isTopicSelectedInModal(topic.name, docFilename))
      .map(topic => ({ topic: topic.name, documentFilename: docFilename }));
    setTempSelectedTopics(prev => [...prev, ...newSelections]);
  };

  // Modal - Deselect all topics from a document
  const deselectAllTopicsInModal = (docFilename: string) => {
    setTempSelectedTopics(prev => prev.filter(t => t.documentFilename !== docFilename));
  };

  // Modal - Check if all topics are selected
  const areAllTopicsSelectedInModal = (docFilename: string) => {
    const docTopics = tempTopicsByDocument[docFilename] || [];
    if (docTopics.length === 0) return false;
    return docTopics.every(topic => isTopicSelectedInModal(topic.name, docFilename));
  };

  // ===== Edit Topics Modal Handlers =====
  // docKey may be a composite selection key ("courseId::filename") or a plain
  // filename (for upload docs).  We store the plain filename in editing state
  // so that API calls and cache updates (which use plain filenames) work
  // without change.  tempTopicsByDocument is looked up by composite key.
  const openEditTopicsModal = (docKey: string, preloadedTopics?: TopicSuggestion[]) => {
    const filename = getFilenameFromKey(docKey);  // plain filename for API/cache
    // Prefer caller-provided topics (avoids React stale-state when called right
    // after a setTopicsCache). Otherwise fall back to caches.
    const docTopics = preloadedTopics
      ?? (topicSource === 'canvas'
          ? (tempTopicsByDocument[docKey] || canvasTopicsCache[filename] || [])
          : (tempTopicsByDocument[docKey] || topicsCache[filename] || []));
    setEditingDocumentFilename(filename);  // always plain filename
    setEditingTopics(docTopics.map(t => t.name));
    setNewTopicInput('');
    setEditingTopicIndex(null);
    setEditingTopicValue('');
    setShowEditTopicsModal(true);
  };

  const closeEditTopicsModal = () => {
    setShowEditTopicsModal(false);
    setEditingDocumentFilename('');
    setEditingTopics([]);
    setNewTopicInput('');
    setEditingTopicIndex(null);
    setEditingTopicValue('');
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
    if (!editingDocumentFilename) return;
    
    // Auto-save the currently editing topic if any
    let topicsToSave = [...editingTopics];
    if (editingTopicIndex !== null && editingTopicValue.trim()) {
      topicsToSave[editingTopicIndex] = editingTopicValue.trim();
      setEditingTopics(topicsToSave);
      setEditingTopicIndex(null);
      setEditingTopicValue('');
    }
    
    setIsSavingTopics(true);
    try {
      // Use appropriate API based on topic source
      const response = topicSource === 'canvas'
        ? await updateCanvasDocumentTopics(editingDocumentFilename, topicsToSave)
        : await updateDocumentTopics(editingDocumentFilename, topicsToSave);
      
      if (response.success) {
        // Update local caches
        const updatedTopics: TopicSuggestion[] = topicsToSave.map((name, idx) => ({
          name,
          relevance_score: 1 - (idx * 0.05),
          description: ''
        }));
        
        // Update appropriate cache based on source
        if (topicSource === 'canvas') {
          setCanvasTopicsCache(prev => ({ ...prev, [editingDocumentFilename]: updatedTopics }));
          setCanvasIndexedDocuments(prev => prev.map(doc => 
            doc.filename === editingDocumentFilename 
              ? { ...doc, topic_count: topicsToSave.length }
              : doc
          ));
        } else {
          setTopicsCache(prev => ({ ...prev, [editingDocumentFilename]: updatedTopics }));
          setIndexedDocuments(prev => prev.map(doc => 
            doc.filename === editingDocumentFilename 
              ? { ...doc, topic_count: topicsToSave.length }
              : doc
          ));
          // Keep the per-row map (used by the Files-đã-upload table) in sync
          // so the topic-count pill updates without needing a hard refresh.
          setIndexedDocsMap(prev => {
            const existing = prev.get(editingDocumentFilename);
            if (!existing) return prev;
            const next = new Map(prev);
            next.set(editingDocumentFilename, { ...existing, topic_count: topicsToSave.length });
            return next;
          });
        }
        
        setTempTopicsByDocument(prev => ({ ...prev, [editingDocumentFilename]: updatedTopics }));
        setTopicsByDocument(prev => ({ ...prev, [editingDocumentFilename]: updatedTopics }));
        setTopicErrorState(prev => ({
          ...prev,
          [getTopicStateKey(topicSource, editingDocumentFilename)]: topicsToSave.length === 0
            ? 'Tai lieu nay chua co chu de nao.'
            : null,
        }));
        
        closeEditTopicsModal();
      } else {
        alert('Không thể lưu chủ đề. Vui lòng thử lại.');
      }
    } catch (error) {
      console.error('Error saving topics:', error);
      alert('Lỗi khi lưu chủ đề. Vui lòng thử lại.');
    } finally {
      setIsSavingTopics(false);
    }
  };

  const handleFileSelect = (event: React.ChangeEvent<HTMLInputElement>) => {
    const files = event.target.files;
    if (files && files.length > 0) {
      const newFiles: UploadFileItem[] = [];
      const errors: string[] = [];
      
      for (let i = 0; i < files.length; i++) {
        const file = files[i];
        if (!file.name.toLowerCase().endsWith('.pdf')) {
          errors.push(file.name);
        } else {
          // Check if file already in queue
          const exists = selectedFiles.some(f => f.file.name === file.name && f.file.size === file.size);
          if (!exists) {
            newFiles.push({
              file,
              status: 'waiting',
            });
          }
        }
      }
      
      if (errors.length > 0) {
        setUploadMessage({ 
          type: 'error', 
          text: `Các file không hỗ trợ (chỉ PDF): ${errors.join(', ')}` 
        });
      } else {
        setUploadMessage(null);
      }
      
      if (newFiles.length > 0) {
        setSelectedFiles(prev => [...prev, ...newFiles]);
        // Set first file as selectedFile for backward compatibility
        if (!selectedFile && newFiles.length > 0) {
          setSelectedFile(newFiles[0].file);
        }
      }
    }
  };

  const removeFileFromQueue = (index: number) => {
    setSelectedFiles(prev => {
      const newList = prev.filter((_, i) => i !== index);
      // Update selectedFile if needed
      if (newList.length === 0) {
        setSelectedFile(null);
      } else if (selectedFile && prev[index]?.file === selectedFile) {
        setSelectedFile(newList[0]?.file || null);
      }
      return newList;
    });
  };

  const clearAllFiles = () => {
    setSelectedFiles([]);
    setSelectedFile(null);
    if (fileInputRef.current) {
      fileInputRef.current.value = '';
    }
    setUploadMessage(null);
  };

  const handleUploadAndIndex = async () => {
    if (selectedFiles.length === 0) {
      setUploadMessage({ type: 'error', text: 'Vui lòng chọn file PDF' });
      return;
    }

    setIsUploading(true);
    setIsProcessingQueue(true);
    setUploadMessage(null);

    // Track results locally
    let successCount = 0;
    let alreadyIndexedCount = 0;
    let errorCount = 0;

    // Process files sequentially via async Celery jobs
    for (let i = 0; i < selectedFiles.length; i++) {
      const fileItem = selectedFiles[i];
      
      // Skip already processed files
      if (fileItem.status !== 'waiting') continue;
      
      // Update status to uploading
      setSelectedFiles(prev => prev.map((f, idx) => 
        idx === i ? { ...f, status: 'uploading' as FileUploadStatus } : f
      ));

      try {
        // Submit async job (file is saved immediately, indexing queued)
        const asyncResp = await asyncUploadAndIndex(fileItem.file);
        const jobId = asyncResp.job_id;

        // Poll until job completes
        let jobResult: JobOut | null = null;
        while (true) {
          const j = await getJob(jobId);
          if (TERMINAL_STATUSES.includes(j.status)) {
            jobResult = j;
            break;
          }
          await new Promise(resolve => setTimeout(resolve, 2000));
        }

        if (jobResult.status === 'SUCCEEDED' && jobResult.result) {
          const result = jobResult.result as {
            success?: boolean;
            already_indexed?: boolean;
            filename?: string;
            pages_loaded?: number;
            chunks_added?: number;
            error?: string;
          };
          if (result.success) {
            if (result.already_indexed) {
              alreadyIndexedCount++;
              setSelectedFiles(prev => prev.map((f, idx) => 
                idx === i ? { 
                  ...f, 
                  status: 'already_indexed' as FileUploadStatus,
                  message: 'Đã có trong cơ sở dữ liệu',
                  details: { filename: result.filename }
                } : f
              ));
            } else {
              successCount++;
              setSelectedFiles(prev => prev.map((f, idx) => 
                idx === i ? { 
                  ...f, 
                  status: 'success' as FileUploadStatus,
                  message: `${result.pages_loaded} trang, ${result.chunks_added} phần nội dung`,
                  details: {
                    filename: result.filename,
                    pages_loaded: result.pages_loaded,
                    chunks_added: result.chunks_added
                  }
                } : f
              ));
            }
          } else {
            errorCount++;
            setSelectedFiles(prev => prev.map((f, idx) => 
              idx === i ? { 
                ...f, 
                status: 'error' as FileUploadStatus,
                message: result.error || 'Lỗi không xác định'
              } : f
            ));
          }
        } else {
          errorCount++;
          setSelectedFiles(prev => prev.map((f, idx) => 
            idx === i ? { 
              ...f, 
              status: 'error' as FileUploadStatus,
              message: jobResult.error_message || 'Lỗi không xác định'
            } : f
          ));
        }
      } catch (error) {
        console.error('Error uploading:', error);
        errorCount++;
        setSelectedFiles(prev => prev.map((f, idx) => 
          idx === i ? { 
            ...f, 
            status: 'error' as FileUploadStatus,
            message: 'Lỗi kết nối server'
          } : f
        ));
      }
    }

    // Reload stats and indexed documents (reset to page 1)
    await loadIndexStats();
    await loadUploadedFiles(1);
    await loadIndexedDocuments(1);
    
    // Clear upload topics cache to reflect new indexed documents
    if (successCount > 0) {
      setTopicsCache({});
    }
    
    setIsUploading(false);
    setIsProcessingQueue(false);
    
    // Summary message with accurate counts
    const totalProcessed = successCount + alreadyIndexedCount + errorCount;
    
    if (errorCount === 0 && totalProcessed > 0) {
      if (alreadyIndexedCount > 0 && successCount === 0) {
        setUploadMessage({ 
          type: 'info', 
          text: `${alreadyIndexedCount} file đã có trong cơ sở dữ liệu từ trước.` 
        });
      } else if (alreadyIndexedCount > 0) {
        setUploadMessage({ 
          type: 'success', 
          text: `Hoàn tất! ${successCount} file mới đã index, ${alreadyIndexedCount} file đã có sẵn.` 
        });
      } else {
        setUploadMessage({ 
          type: 'success', 
          text: `Hoàn tất! ${successCount} file đã được index thành công.` 
        });
      }
    } else if (errorCount > 0) {
      setUploadMessage({ 
        type: 'info', 
        text: `Xử lý xong: ${successCount} thành công, ${alreadyIndexedCount} đã có sẵn, ${errorCount} lỗi.` 
      });
    }
  };



  const handleResetIndex = async () => {
    const ok = await confirmDialog({
      title: 'Xóa toàn bộ dữ liệu tải lên?',
      message:
        'Bạn có chắc muốn xóa toàn bộ dữ liệu RAG cá nhân?\n\n' +
        'Thao tác này sẽ:\n' +
        '• Xóa tất cả file PDF đã tải lên khỏi máy chủ\n' +
        '• Xóa toàn bộ index (chunks + embeddings)\n' +
        '• Xóa tất cả chủ đề đã trích xuất\n\n' +
        'Hành động này không thể hoàn tác.',
      confirmLabel: 'Xóa tất cả',
      cancelLabel: 'Hủy',
      tone: 'danger',
    });
    if (!ok) {
      return;
    }

    setIsResetting(true);

    try {
      const response = await resetRAGIndex();
      if (response.success) {
        const deleted = (response as { deleted_files?: number }).deleted_files;
        setUploadMessage({
          type: 'success',
          text: typeof deleted === 'number'
            ? `Đã xóa toàn bộ dữ liệu (${deleted} file PDF + index + chủ đề).`
            : 'Đã xóa toàn bộ dữ liệu thành công.',
        });
        setGeneratedQuiz([]);
        setQuizMessage(null);
        setTopicsCache({});
        await Promise.all([
          loadIndexStats(),
          loadIndexedDocuments(1),
          loadUploadedFiles(1),
        ]);
      } else {
        setUploadMessage({ type: 'error', text: response.error || 'Lỗi khi xóa dữ liệu' });
      }
    } catch (error) {
      console.error('Reset error:', error);
      setUploadMessage({ type: 'error', text: 'Lỗi khi xóa dữ liệu' });
    } finally {
      setIsResetting(false);
    }
  };

  // ===== Per-uploaded-file action handlers =====
  const [busyDocAction, setBusyDocAction] = useState<Record<string, 'remove' | 'extract' | 'edit' | 'index'>>({});

  const setDocBusy = (filename: string, action: 'remove' | 'extract' | 'edit' | 'index' | null) => {
    setBusyDocAction(prev => {
      const next = { ...prev };
      if (action === null) {
        delete next[filename];
      } else {
        next[filename] = action;
      }
      return next;
    });
  };

  const isFilenameIndexed = (filename: string): boolean => {
    if (indexedDocsMap.has(filename)) return true;
    return indexedDocuments.some(d => d.filename === filename);
  };

  const handleRemoveDocIndex = async (filename: string) => {
    const ok = await confirmDialog({
      title: 'Xóa file và dữ liệu liên quan?',
      message:
        `Bạn có chắc muốn xóa "${filename}"?\n\n` +
        `Thao tác này sẽ:\n` +
        `• Xóa file PDF đã tải lên khỏi máy chủ\n` +
        `• Xóa toàn bộ index (chunks + embeddings) của file\n` +
        `• Xóa các chủ đề đã trích xuất cho file\n\n` +
        `Hành động này không thể hoàn tác.`,
      confirmLabel: 'Xóa tất cả',
      cancelLabel: 'Hủy',
      tone: 'danger',
    });
    if (!ok) return;

    setDocBusy(filename, 'remove');
    try {
      // 1) Drop the RAG index (Chroma collection + topics + DB row).
      // Ignored if the file was never indexed — we still proceed to delete
      // the on-disk PDF below.
      const indexed = isFilenameIndexed(filename);
      let indexErr: string | null = null;
      if (indexed) {
        try {
          const idxRes = await removeDocumentIndex(filename);
          if (!idxRes.success) {
            indexErr = 'Không xóa được index';
          }
        } catch (err) {
          console.error('removeDocumentIndex failed:', err);
          indexErr = 'Lỗi khi xóa index';
        }
      }

      // 2) Delete the source PDF from the user's upload directory.
      try {
        await deleteUploadedFile(filename);
      } catch (err) {
        console.error('deleteUploadedFile failed:', err);
        setUploadMessage({
          type: 'error',
          text: indexErr
            ? `${indexErr}; ngoài ra không xóa được file PDF.`
            : 'Không xóa được file PDF',
        });
        return;
      }

      // 3) Drop cached topics + reload UI.
      setTopicsCache(prev => {
        const next = { ...prev };
        delete next[filename];
        return next;
      });
      await Promise.all([
        loadIndexStats(),
        loadIndexedDocuments(1),
        loadUploadedFiles(uploadedPage),
      ]);

      if (indexErr) {
        setUploadMessage({
          type: 'info',
          text: `Đã xóa file PDF "${filename}" nhưng không xóa được index (${indexErr}).`,
        });
      } else {
        setUploadMessage({
          type: 'success',
          text: indexed
            ? `Đã xóa file và toàn bộ dữ liệu liên quan: ${filename}`
            : `Đã xóa file: ${filename}`,
        });
      }
    } finally {
      setDocBusy(filename, null);
    }
  };

  const handleIndexFile = async (filename: string) => {
    setDocBusy(filename, 'index');
    try {
      const resp = await asyncBuildIndex(filename);
      const jobId = resp.job_id;

      let final: JobOut | null = null;
      while (true) {
        const j = await getJob(jobId);
        if (TERMINAL_STATUSES.includes(j.status)) {
          final = j;
          break;
        }
        await new Promise(r => setTimeout(r, 1500));
      }

      if (final.status === 'SUCCEEDED') {
        const result = (final.result || {}) as {
          success?: boolean;
          already_indexed?: boolean;
          pages_loaded?: number;
          chunks_added?: number;
          error?: string;
        };
        if (result.success) {
          await Promise.all([
            loadIndexStats(),
            loadIndexedDocuments(1),
          ]);
          setUploadMessage({
            type: 'success',
            text: result.already_indexed
              ? `File đã có trong index: ${filename}`
              : `Đã index file: ${filename} (${result.pages_loaded ?? 0} trang, ${result.chunks_added ?? 0} chunks)`,
          });
        } else {
          setUploadMessage({
            type: 'error',
            text: `Index thất bại: ${result.error || 'Lỗi không xác định'}`,
          });
        }
      } else {
        setUploadMessage({
          type: 'error',
          text: `Index thất bại: ${final.error_message || 'Lỗi không xác định'}`,
        });
      }
    } catch (e) {
      console.error('Index file error:', e);
      setUploadMessage({ type: 'error', text: 'Lỗi khi index file' });
    } finally {
      setDocBusy(filename, null);
    }
  };

  const handleExtractDocTopics = async (filename: string) => {
    setDocBusy(filename, 'extract');
    try {
      const resp = await asyncExtractTopicsForDocument(filename);
      const jobId = resp.job_id;

      // Poll until done
      let final: JobOut | null = null;
      while (true) {
        const j = await getJob(jobId);
        if (TERMINAL_STATUSES.includes(j.status)) {
          final = j;
          break;
        }
        await new Promise(r => setTimeout(r, 1500));
      }

      if (final.status === 'SUCCEEDED') {
        // Invalidate cached topics so the modal/picker re-fetches
        setTopicsCache(prev => {
          const next = { ...prev };
          delete next[filename];
          return next;
        });
        await loadIndexedDocuments(1);
        setUploadMessage({ type: 'success', text: `Đã trích xuất chủ đề cho: ${filename}` });
      } else {
        setUploadMessage({
          type: 'error',
          text: `Trích xuất chủ đề thất bại: ${final.error_message || 'Lỗi không xác định'}`,
        });
      }
    } catch (e) {
      console.error('Extract topics error:', e);
      setUploadMessage({ type: 'error', text: 'Lỗi khi trích xuất chủ đề' });
    } finally {
      setDocBusy(filename, null);
    }
  };

  const handleEditDocTopics = async (filename: string) => {
    setDocBusy(filename, 'edit');
    try {
      // Make sure we're editing the upload-source list, and topics are loaded.
      if (topicSource !== 'upload') {
        setTopicSource('upload');
      }
      // Always re-fetch fresh topics from backend so the modal is never stale,
      // and pass them directly to avoid React's async state update lag (which
      // previously caused the first open to show "no topics").
      let preloaded: TopicSuggestion[] | undefined = topicsCache[filename];
      try {
        const resp = await getDocumentTopics(filename);
        if (resp.success && resp.topics) {
          const topicsList: TopicSuggestion[] = resp.topics.map(name => ({
            name,
            description: '',
            keywords: [],
          }));
          setTopicsCache(prev => ({ ...prev, [filename]: topicsList }));
          preloaded = topicsList;
        }
      } catch (err) {
        console.warn('Could not preload topics for edit:', err);
      }
      openEditTopicsModal(filename, preloaded);
    } finally {
      setDocBusy(filename, null);
    }
  };

  // Quiz generation handler
  const handleGenerateQuiz = async () => {
    // Build topics list from selectedTopics or quizTopic
    const topicsList: string[] = selectedTopics.length > 0 
      ? selectedTopics.map(t => t.topic)
      : quizTopic.trim() ? [quizTopic.trim()] : [];
    
    if (topicsList.length === 0) {
      setQuizMessage(null);
      setQuizError('Vui lòng chọn chủ đề quiz hoặc nhập chủ đề');
      return;
    }

    setIsGeneratingQuiz(true);
    setQuizError(null);
    setQuizMessage(null);
    setGeneratedQuiz([]);
    setEditingQuestionIndex(null);
    setEditingQuestion(null);

    // Derive selected_documents from topics' source documents.
    // selectedTopics.documentFilename now holds a composite selection key
    // ("courseId::filename" for Canvas, plain "filename" for uploads).
    const docsFromTopicsKeys = selectedTopics.length > 0
      ? [...new Set(selectedTopics.map(t => t.documentFilename))]
      : undefined;

    // Extract plain filenames for the backend API (backend never sees composite keys)
    const docsFromTopics = docsFromTopicsKeys?.map(getFilenameFromKey);

    const quizRequest = {
      topics: topicsList,
      num_questions: numQuestions,
      difficulty: quizDifficulty,
      language: quizLanguage,
      selected_documents: docsFromTopics,
    };

    // V2: attach course-domain hints only for Canvas quiz generation.
    // Canvas requires an explicit course_id — extract it directly from the
    // composite selection keys (which already embed course_id), so we are
    // immune to filename collisions across courses.
    let canvasCourseId: number | null = null;
    if (topicSource === 'canvas') {
      const targetKeys = docsFromTopicsKeys ?? [];
      const courseIdSet = new Set<number>();
      for (const key of targetKeys) {
        const courseId = getCourseIdFromKey(key);
        if (typeof courseId === 'number') courseIdSet.add(courseId);
      }
      if (courseIdSet.size === 1) {
        canvasCourseId = courseIdSet.values().next().value as number;
      } else if (courseIdSet.size === 0) {
        setQuizMessage(null);
        setQuizError('Không xác định được khoá học cho các tài liệu đã chọn. Hãy chọn lại từ danh sách Canvas.');
        setIsGeneratingQuiz(false);
        return;
      } else {
        setQuizMessage(null);
        setQuizError('Các tài liệu đã chọn thuộc nhiều khoá học khác nhau. Vui lòng chỉ chọn tài liệu trong cùng một khoá học để tạo quiz.');
        setIsGeneratingQuiz(false);
        return;
      }
    }

    const canvasQuizRequest =
      topicSource === 'canvas'
        ? {
            ...quizRequest,
            course_id: canvasCourseId as number,
            ...(publicConfig?.enable_course_domain_docs
              ? {
                  include_course_domain: includeCourseDomain,
                  domain_quota_ratio: Math.min(0.6, Math.max(0, domainQuotaPct / 100)),
                }
              : {}),
          }
        : quizRequest;

    try {
      if (topicSource === 'canvas') {
        // Canvas quiz — async via Celery. course_id is guaranteed above
        // (the canvas branch above either set it or aborted early).
        await quizJob.startJob(() =>
          asyncCanvasGenerateQuiz({
            ...canvasQuizRequest,
            course_id: canvasCourseId as number,
          }),
        );
        // Result handled by useEffect on quizJob.job.status
      } else {
        // Document RAG quiz — async via Celery
        await quizJob.startJob(() => asyncGenerateQuiz(quizRequest));
        // Result handled by useEffect on quizJob.job.status
      }
    } catch (error) {
      console.error('Quiz generation error:', error);
      setQuizMessage(null);
      setQuizError('Lỗi khi tạo quiz. Hãy kiểm tra hệ thống AI đang hoạt động và có tài liệu đã được xử lý.');
      setIsGeneratingQuiz(false);
    }
  };

  // Start editing a specific question
  const handleStartEdit = (index: number) => {
    setEditingQuestionIndex(index);
    setEditingQuestion(JSON.parse(JSON.stringify(generatedQuiz[index])));
  };

  // Update the currently editing question
  const handleEditQuestion = (field: string, value: any) => {
    if (!editingQuestion) return;
    
    const updated = { ...editingQuestion };
    if (field === 'option') {
      const [optionKey, optionValue] = value as [string, string];
      updated.options = {
        ...updated.options,
        [optionKey]: optionValue
      };
    } else {
      (updated as any)[field] = value;
    }
    setEditingQuestion(updated);
  };

  // Save a single question
  const handleSaveQuestion = () => {
    if (editingQuestionIndex === null || !editingQuestion) return;
    
    const updated = [...generatedQuiz];
    updated[editingQuestionIndex] = editingQuestion;
    setGeneratedQuiz(updated);
    setEditingQuestionIndex(null);
    setEditingQuestion(null);
  };

  // Cancel editing a single question
  const handleCancelEdit = () => {
    setEditingQuestionIndex(null);
    setEditingQuestion(null);
  };

  // Generate QTI blob and open Canvas import modal
  const handleExportQTI = async () => {
    if (generatedQuiz.length === 0) {
      setQuizError('Không có quiz để export');
      return;
    }

    setIsExporting(true);
    try {
      const blob = await exportQuizToQTI(generatedQuiz, quizTopic || 'Generated Quiz');
      
      // Store the blob and open the Canvas import modal
      setQtiZipBlob(blob);
      setShowCanvasImportModal(true);
    } catch (error) {
      console.error('Export error:', error);
      setQuizError('Lỗi khi tạo QTI package');
    } finally {
      setIsExporting(false);
    }
  };

  // Download QTI as local file (alternative to Canvas import)
  const handleDownloadQTI = async () => {
    if (generatedQuiz.length === 0) {
      setQuizError('Không có quiz để download');
      return;
    }

    setIsExporting(true);
    try {
      const blob = await exportQuizToQTI(generatedQuiz, quizTopic || 'Generated Quiz');
      
      // Download ZIP file locally
      const url = window.URL.createObjectURL(blob);
      const link = document.createElement('a');
      link.href = url;
      link.download = `quiz_${quizTopic.replace(/\s+/g, '_')}.zip`;
      document.body.appendChild(link);
      link.click();
      document.body.removeChild(link);
      window.URL.revokeObjectURL(url);
    } catch (error) {
      console.error('Download error:', error);
      setQuizError('Lỗi khi download quiz');
    } finally {
      setIsExporting(false);
    }
  };

  // Open the "Save to Kho Đề" modal — pre-fills sensible defaults so the
  // user can review or edit the title/description/tags before committing.
  const openSaveQuizModal = () => {
    if (generatedQuiz.length === 0) return;
    const defaultTitle = quizTopic
      ? `Quiz - ${quizTopic}`
      : selectedTopics.length > 0
        ? `Quiz - ${selectedTopics.map(t => t.topic).slice(0, 3).join(', ')}${selectedTopics.length > 3 ? '…' : ''}`
        : `Quiz ${new Date().toLocaleString('vi-VN')}`;
    setSaveQuizTitle(defaultTitle);
    setSaveQuizDescription('');
    setSaveQuizTagsInput(selectedTopics.map(t => t.topic).join(', '));
    setSaveQuizError(null);
    setSaveLibrarySuccess(false);
    setShowSaveQuizModal(true);
  };

  // Save generated quiz to Kho Đề (called from modal "Lưu" button).
  const confirmSaveQuiz = async () => {
    if (generatedQuiz.length === 0) return;
    const title = saveQuizTitle.trim();
    if (!title) {
      setSaveQuizError('Vui lòng nhập tên quiz.');
      return;
    }
    setSaveQuizError(null);
    setIsSavingToLibrary(true);
    setSaveLibrarySuccess(false);
    try {
      // Try to resolve course info from selected canvas documents.
      // selectedTopics[0].documentFilename is now a composite selection key;
      // extract filename and course_id from it for the lookup.
      let courseId: number | null = null;
      let courseName: string | null = null;
      if (topicSource === 'canvas' && selectedTopics.length > 0) {
        const firstKey = selectedTopics[0].documentFilename;
        const firstFilename = getFilenameFromKey(firstKey);
        const firstCourseId = getCourseIdFromKey(firstKey);
        const firstDoc = canvasIndexedDocuments.find(
          d => d.filename === firstFilename && d.course_id === firstCourseId,
        );
        if (firstDoc?.course_id) {
          courseId = firstDoc.course_id;
          courseName = firstDoc.course_name || courseNameMap[firstDoc.course_id] || null;
        }
      }

      const questions = generatedQuiz.map((q, idx) => ({
        question_number: idx + 1,
        question_text: q.question,
        options: q.options as Record<string, string>,
        correct_answer: q.correct_answer ?? 'A',
        explanation: null,
        question_type: 'multiple_choice' as const,
        points: 1.0,
      }));

      const tags = saveQuizTagsInput
        .split(',')
        .map(t => t.trim())
        .filter(Boolean);

      await savedQuizApi.create({
        title,
        description: saveQuizDescription.trim() || null,
        course_id: courseId,
        course_name: courseName,
        difficulty: quizDifficulty,
        language: quizLanguage,
        source: topicSource === 'canvas' ? 'canvas_rag' : 'rag',
        source_job_id: null,
        tags,
        questions,
      });
      setSaveLibrarySuccess(true);
      setShowSaveQuizModal(false);
      setTimeout(() => setSaveLibrarySuccess(false), 3000);
    } catch (err) {
      console.error('[DocumentRAG] Save to library failed:', err);
      const msg =
        (err as { response?: { data?: { detail?: string } } })?.response?.data?.detail
        || (err as Error)?.message
        || 'Lỗi khi lưu vào Kho Đề.';
      setSaveQuizError(msg);
    } finally {
      setIsSavingToLibrary(false);
    }
  };

  const formatFileSize = (bytes: number): string => {
    if (bytes < 1024) return `${bytes} B`;
    if (bytes < 1024 * 1024) return `${(bytes / 1024).toFixed(1)} KB`;
    return `${(bytes / (1024 * 1024)).toFixed(1)} MB`;
  };

  return (
    <div className="document-rag-panel">
      {/* ---- Decorative background (matching Chat panel) ---- */}
      <div className="rag-bg-decoration">
        <div className="rag-bg-orb rag-bg-orb-1" />
        <div className="rag-bg-orb rag-bg-orb-2" />
        <div className="rag-bg-orb rag-bg-orb-3" />
      </div>
      <div className="rag-stars">
        {ragStars.map((s) => (
          <span
            key={s.id}
            className="rag-star"
            style={{ top: s.top, left: s.left, '--duration': s.duration, '--delay': s.delay, width: s.size, height: s.size } as React.CSSProperties}
          />
        ))}
      </div>
      <div className="rag-glow-line rag-glow-line-1" />
      <div className="rag-glow-line rag-glow-line-2" />

      <div className="rag-hero-header">
        <div className="rag-hero-icon">
          <FileText size={28} />
        </div>
        <div className="rag-hero-text">
          <h2>RAG Tài liệu</h2>
          <p>Upload tài liệu PDF và tạo quiz thông minh</p>
        </div>

        {/* AI Status Chips — integrated into header */}
        <div className="rag-header-chips">
          <div className="rag-chip rag-chip-provider">
            <Zap size={13} />
            <span className="rag-chip-text">⚡ Groq</span>
          </div>
          <div className="rag-chip-divider" />
          <div className={`rag-chip rag-chip-model ${llmStatus?.connected ? 'connected' : 'disconnected'}`}>
            {llmStatus?.connected ? (
              <>
                <CheckCircle size={12} className="rag-chip-status-icon" />
                <span className="rag-chip-model-name">{llmProviderInfo?.current_model || llmStatus.model || 'Sẵn sàng'}</span>
              </>
            ) : (
              <>
                <AlertCircle size={12} className="rag-chip-status-icon" />
                <span className="rag-chip-text disconnected">Chưa sẵn sàng</span>
              </>
            )}
          </div>
        </div>

        <button
          className="btn-hero-refresh"
          onClick={() => {
            loadIndexStats();
            loadLLMStatus();
            loadUploadedFiles();
            loadLLMProviderInfo();
          }}
          title="Làm mới trạng thái"
          aria-label="Làm mới trạng thái"
        >
          <RefreshCw size={18} />
        </button>
        <PanelHelpButton panelKey="document_rag" />
      </div>

      <div className="rag-content">

        {/* Upload Section - Full Width */}
        <div className="upload-section-redesign">
          <div className="upload-section-compact">

              <h3>
                <Upload size={18} />
                Tải lên tài liệu PDF
                {selectedFiles.length > 0 && (
                  <span className="files-count-badge">{selectedFiles.length} file</span>
                )}
              </h3>
              
              {/* Drop Zone */}
              <div className="upload-area-compact">
                <input
                  type="file"
                  ref={fileInputRef}
                  accept=".pdf"
                  multiple
                  onChange={handleFileSelect}
                  className="file-input"
                  id="pdf-upload"
                  disabled={isProcessingQueue}
                />
                <label 
                  htmlFor="pdf-upload" 
                  className={`file-label-compact ${selectedFiles.length > 0 ? 'has-file' : ''} ${isProcessingQueue ? 'disabled' : ''}`}
                >
                  <div className="upload-icon-wrapper">
                    {selectedFiles.length > 0 ? <FileUp size={28} /> : <Upload size={28} />}
                  </div>
                  <div className="upload-text">
                    <span className="upload-main-text">
                      {selectedFiles.length > 0 
                        ? `${selectedFiles.length} file đã chọn` 
                        : 'Chọn hoặc kéo thả file PDF'}
                    </span>
                    <span className="upload-hint">
                      <FileText size={14} />
                      Hỗ trợ nhiều file PDF, tối đa 50MB/file
                    </span>
                  </div>
                  {selectedFiles.length > 0 && !isProcessingQueue && (
                    <button 
                      type="button"
                      className="btn-add-more"
                      onClick={(e) => {
                        e.preventDefault();
                        e.stopPropagation();
                        fileInputRef.current?.click();
                      }}
                    >
                      <Plus size={16} />
                      Thêm file
                    </button>
                  )}
                </label>
              </div>

              {/* Files Queue List */}
              {selectedFiles.length > 0 && (
                <div className="files-queue">
                  <div className="files-queue-header">
                    <span className="queue-title">
                      <FileIcon size={16} />
                      Danh sách file ({selectedFiles.length})
                    </span>
                    {!isProcessingQueue && (
                      <button 
                        type="button" 
                        className="btn-clear-all-files"
                        onClick={clearAllFiles}
                      >
                        <Trash2 size={14} />
                        Xóa tất cả
                      </button>
                    )}
                  </div>
                  
                  <div className="files-list">
                    {selectedFiles.map((fileItem, index) => (
                      <div 
                        key={`${fileItem.file.name}-${index}`} 
                        className={`file-queue-item status-${fileItem.status}`}
                      >
                        <div className="file-queue-icon">
                          {fileItem.status === 'waiting' && <Clock size={18} />}
                          {fileItem.status === 'uploading' && <Loader2 size={18} className="spin" />}
                          {fileItem.status === 'success' && <CheckCircle size={18} />}
                          {fileItem.status === 'error' && <XCircle size={18} />}
                          {fileItem.status === 'already_indexed' && <Database size={18} />}
                        </div>
                        
                        <div className="file-queue-info">
                          <span className="file-queue-name">{fileItem.file.name}</span>
                          <div className="file-queue-meta">
                            <span className="file-queue-size">{formatFileSize(fileItem.file.size)}</span>
                            {fileItem.status === 'waiting' && (
                              <span className="file-queue-status waiting">Chờ xử lý</span>
                            )}
                            {fileItem.status === 'uploading' && (
                              <span className="file-queue-status uploading">Đang index...</span>
                            )}
                            {fileItem.status === 'success' && (
                              <span className="file-queue-status success">{fileItem.message}</span>
                            )}
                            {fileItem.status === 'error' && (
                              <span className="file-queue-status error">{fileItem.message}</span>
                            )}
                            {fileItem.status === 'already_indexed' && (
                              <span className="file-queue-status already-indexed">Đã có trong CSDL</span>
                            )}
                          </div>
                        </div>
                        
                        {fileItem.status === 'waiting' && !isProcessingQueue && (
                          <button 
                            type="button"
                            className="btn-remove-file"
                            onClick={() => removeFileFromQueue(index)}
                            aria-label={`Xóa ${fileItem.file.name} khỏi danh sách`}
                            title="Xóa khỏi danh sách"
                          >
                            <X size={16} />
                          </button>
                        )}
                      </div>
                    ))}
                  </div>
                  
                  {/* Progress Summary */}
                  {isProcessingQueue && (
                    <div className="upload-progress-summary">
                      <div className="progress-bar">
                        <div 
                          className="progress-fill"
                          style={{ 
                            width: `${(selectedFiles.filter(f => f.status !== 'waiting' && f.status !== 'uploading').length / selectedFiles.length) * 100}%` 
                          }}
                        />
                      </div>
                      <span className="progress-text">
                        {selectedFiles.filter(f => f.status !== 'waiting' && f.status !== 'uploading').length} / {selectedFiles.length} hoàn tất
                      </span>
                    </div>
                  )}
                </div>
              )}

              <div className="upload-actions-compact">
                {(() => {
                  const waitingCount = selectedFiles.filter(f => f.status === 'waiting').length;
                  const uploadDisabled =
                    selectedFiles.length === 0 || isUploading || waitingCount === 0;
                  const uploadReason = isUploading
                    ? 'Đang xử lý, vui lòng đợi...'
                    : selectedFiles.length === 0
                      ? 'Hãy chọn ít nhất một file PDF trước'
                      : waitingCount === 0
                        ? 'Tất cả file đã được xử lý hoặc đang chờ'
                        : 'Tải lên & xử lý các file đã chọn';
                  return (
                    <button
                      className="btn btn-primary btn-upload-main"
                      onClick={handleUploadAndIndex}
                      disabled={uploadDisabled}
                      aria-disabled={uploadDisabled}
                      title={uploadReason}
                    >
                      {isUploading ? (
                        <>
                          <Loader2 size={16} className="spin" />
                          Đang xử lý...
                        </>
                      ) : (
                        <>
                          <Database size={16} />
                          Tải lên & Xử lý {waitingCount > 0 && `(${waitingCount} file)`}
                        </>
                      )}
                    </button>
                  );
                })()}

                <button
                  className="btn btn-outline-danger btn-reset"
                  onClick={handleResetIndex}
                  disabled={isResetting || ((indexStats?.total_documents ?? 0) === 0 && uploadedTotal === 0)}
                  aria-disabled={isResetting || ((indexStats?.total_documents ?? 0) === 0 && uploadedTotal === 0)}
                  title={
                    isResetting
                      ? 'Đang xóa, vui lòng đợi...'
                      : ((indexStats?.total_documents ?? 0) === 0 && uploadedTotal === 0)
                        ? 'Chưa có dữ liệu nào để xóa'
                        : 'Xóa toàn bộ file PDF đã tải lên + index + chủ đề (không thể hoàn tác)'
                  }
                >
                  {isResetting ? (
                    <Loader2 size={16} className="spin" />
                  ) : (
                    <Trash2 size={16} />
                  )}
                  Xóa dữ liệu
                </button>
              </div>

              {uploadMessage && (
                <div className={`message message-compact ${uploadMessage.type}`}>
                  {uploadMessage.type === 'success' && <CheckCircle size={16} />}
                  {uploadMessage.type === 'error' && <AlertCircle size={16} />}
                  {uploadMessage.type === 'info' && <Info size={16} />}
                  {uploadMessage.text}
                </div>
              )}
          </div>
        </div>

        {/* Quiz Generation Section */}
          <div className="quiz-section">
            <h3>
              <BookOpen size={18} />
              Tạo Quiz từ tài liệu
            </h3>

            <div className="quiz-form">
              {/* Topic Selection Button & Preview */}
              <div className="topic-selector-section">
                <label className="section-label">
                  <FileText size={16} />
                  Chủ đề quiz
                </label>
                
                {selectedTopics.length > 0 ? (
                  <div className="selected-topics-preview">
                    <div className="selected-topics-header">
                      <span className="selected-count">
                        <CheckCircle size={16} />
                        {selectedTopics.length} chủ đề từ {selectedDocuments.length} tài liệu
                      </span>
                      <div className="preview-actions">
                        <button type="button" className="btn-edit-topics" onClick={openTopicModal}>
                          <Edit2 size={14} /> Sửa
                        </button>
                        <button type="button" className="btn-clear-all" onClick={clearSelectedTopics}>
                          <X size={14} /> Xóa tất cả
                        </button>
                      </div>
                    </div>
                    <div className="selected-topics-chips">
                      {selectedTopics.slice(0, 5).map((st, idx) => (
                        <span key={idx} className="topic-chip">
                          {st.topic}
                        </span>
                      ))}
                      {selectedTopics.length > 5 && (
                        <span className="topic-chip more">+{selectedTopics.length - 5} khác</span>
                      )}
                    </div>
                  </div>
                ) : (
                  <button 
                    type="button" 
                    className="btn-select-topics"
                    onClick={openTopicModal}
                    disabled={indexedTotal === 0 && canvasIndexedDocuments.length === 0}
                  >
                    <BookOpen size={18} />
                    <span>Chọn chủ đề từ tài liệu</span>
                    <ChevronDown size={18} />
                  </button>
                )}
                
                {indexedTotal === 0 && canvasIndexedDocuments.length === 0 && (
                  <p className="no-docs-hint">
                    <Info size={14} />
                    Chưa có tài liệu. Hãy upload tài liệu hoặc tải từ Canvas LMS.
                  </p>
                )}
              </div>

              <div className="form-row">
                <div className="form-group">
                  <label>Số câu hỏi</label>
                  <select
                    value={numQuestions}
                    onChange={(e) => setNumQuestions(Number(e.target.value))}
                    disabled={isGeneratingQuiz}
                  >
                    {[3, 5, 7, 10, 15, 20, 30, 40].map(n => (
                      <option key={n} value={n}>{n} câu</option>
                    ))}
                  </select>
                </div>

                <div className="form-group">
                  <label>Độ khó</label>
                  <select
                    value={quizDifficulty}
                    onChange={(e) => setQuizDifficulty(e.target.value as 'easy' | 'medium' | 'hard')}
                    disabled={isGeneratingQuiz}
                  >
                    <option value="easy">Dễ</option>
                    <option value="medium">Trung bình</option>
                    <option value="hard">Khó</option>
                  </select>
                </div>

                <div className="form-group">
                  <label>Ngôn ngữ</label>
                  <select
                    value={quizLanguage}
                    onChange={(e) => setQuizLanguage(e.target.value as 'vi' | 'en')}
                    disabled={isGeneratingQuiz}
                  >
                    <option value="vi">Tiếng Việt</option>
                    <option value="en">English</option>
                  </select>
                </div>
              </div>

              {topicSource === 'canvas' && publicConfig?.enable_course_domain_docs && (
                <div
                  className="form-section"
                  style={{
                    margin: '12px 0 16px',
                    padding: 12,
                    border: '1px solid rgba(56,189,248,0.25)',
                    borderRadius: 6,
                    background: 'rgba(56,189,248,0.04)',
                  }}
                >
                  <label
                    style={{
                      display: 'flex',
                      alignItems: 'center',
                      gap: 8,
                      fontSize: 13,
                      fontWeight: 500,
                      color: '#e2e8f0',
                      cursor: isGeneratingQuiz ? 'not-allowed' : 'pointer',
                    }}
                  >
                    <input
                      type="checkbox"
                      checked={includeCourseDomain}
                      disabled={isGeneratingQuiz}
                      onChange={(e) => setIncludeCourseDomain(e.target.checked)}
                    />
                    Bao gồm tri thức nền dùng chung của khóa học
                  </label>
                  <p style={{
                    margin: '6px 0 10px 24px',
                    fontSize: 11,
                    color: '#94a3b8',
                    lineHeight: 1.45,
                  }}>
                    Bổ sung ngữ cảnh từ các tài liệu Canvas được giảng viên đánh dấu dùng chung cho khóa học. Tài liệu cá nhân tải lên sẽ không được sử dụng.
                  </p>

                  {includeCourseDomain && (
                    <div style={{ marginLeft: 24 }}>
                      <label style={{
                        display: 'block',
                        fontSize: 12,
                        color: '#cbd5e1',
                        marginBottom: 4,
                      }}>
                        Domain ratio: <strong>{domainQuotaPct}%</strong>
                        <span style={{ color: '#64748b', marginLeft: 6 }}>
                          (of retrieved context budget)
                        </span>
                      </label>
                      <input
                        type="range"
                        min={0}
                        max={60}
                        step={5}
                        value={domainQuotaPct}
                        disabled={isGeneratingQuiz}
                        onChange={(e) => setDomainQuotaPct(Number(e.target.value))}
                        style={{ width: '100%', maxWidth: 320 }}
                      />
                    </div>
                  )}
                </div>
              )}

              {(() => {
                const noTopics = selectedTopics.length === 0;
                const noDocs = indexedTotal === 0 && canvasIndexedDocuments.length === 0;
                const generateDisabled = noTopics || isGeneratingQuiz || noDocs;
                const generateReason = isGeneratingQuiz
                  ? 'Đang tạo quiz, vui lòng đợi...'
                  : noDocs
                    ? 'Bạn cần index ít nhất một tài liệu trước khi tạo quiz'
                    : noTopics
                      ? 'Hãy chọn ít nhất một chủ đề'
                      : `Tạo quiz cho ${selectedTopics.length} chủ đề đã chọn`;
                return (
                  <button
                    className="btn btn-primary btn-generate"
                    onClick={handleGenerateQuiz}
                    disabled={generateDisabled}
                    aria-disabled={generateDisabled}
                    title={generateReason}
                  >
                    {isGeneratingQuiz ? (
                      <>
                        <Loader2 size={16} className="spin" />
                        Đang tạo quiz...
                      </>
                    ) : (
                      <>
                        <BookOpen size={16} />
                        Tạo Quiz {selectedTopics.length > 0 ? `(${selectedTopics.length} chủ đề)` : ''}
                      </>
                    )}
                  </button>
                );
              })()}

              {indexedTotal === 0 && canvasIndexedDocuments.length === 0 && (
                <div className="message info">
                  <Info size={16} />
                  Vui lòng upload và index tài liệu PDF hoặc tải từ Canvas LMS trước khi tạo quiz.
                </div>
              )}

              {quizMessage && !quizError && (
                <div className="message info">
                  <Info size={16} />
                  {quizMessage}
                </div>
              )}

              {quizError && (
                <div className="message error">
                  <AlertCircle size={16} />
                  {quizError}
                </div>
              )}
            </div>

            {/* Generated Quiz Preview Button */}
            {generatedQuiz.length > 0 && (
              <div className="quiz-preview-section">
                <div className="quiz-preview-card">
                  <div className="quiz-preview-info">
                    <HelpCircle size={20} className="quiz-icon" />
                    <div className="quiz-preview-details">
                      <span className="quiz-preview-title">Quiz đã tạo</span>
                      <span className="quiz-preview-meta">{generatedQuiz.length} câu hỏi về "{selectedTopics.length > 0 ? selectedTopics.map(t => t.topic).join(', ') : quizTopic}"</span>
                    </div>
                  </div>
                  <div className="quiz-preview-actions">
                    <button
                      className="btn btn-primary"
                      onClick={() => setShowQuizModal(true)}
                    >
                      <BookOpen size={16} />
                      Xem Quiz
                    </button>
                    <button
                      className="btn btn-secondary btn-new-quiz"
                      onClick={() => {
                        setGeneratedQuiz([]);
                        setQuizMessage(null);
                        setQuizError(null);
                        setEditingQuestionIndex(null);
                        setEditingQuestion(null);
                      }}
                    >
                      <RefreshCw size={16} />
                      Tạo mới
                    </button>
                  </div>
                </div>
              </div>
            )}
          </div>

        {/* Uploaded Files List */}
        {(uploadedFiles.length > 0 || uploadedTotal > 0) && (
          <div className="files-section">
            <div className="section-header">
              <h3>
                <FileIcon size={18} />
                Files đã upload
                <span className="indexed-count-badge">{uploadedTotal}</span>
              </h3>
              <div className="section-actions">
                <button
                  type="button"
                  className="btn-secondary btn-sm"
                  onClick={() => {
                    void loadUploadedFiles(uploadedPage);
                    void loadIndexedFilenameMap();
                  }}
                  title="Tải lại danh sách file"
                >
                  <RefreshCw size={14} />
                  Làm mới
                </button>
              </div>
            </div>
            <div className="files-list">
              <table className="files-table rag-uploaded-files-table">
                <colgroup>
                  <col className="col-name" />
                  <col className="col-size" />
                  <col className="col-topics" />
                  <col className="col-status" />
                  <col className="col-actions" />
                </colgroup>
                <thead>
                  <tr>
                    <th>Tên file</th>
                    <th>Kích thước</th>
                    <th>Chủ đề</th>
                    <th>Trạng thái</th>
                    <th className="actions-col">Thao tác</th>
                  </tr>
                </thead>
                <tbody>
                  {uploadedFiles.map((file) => {
                    const indexed = isFilenameIndexed(file.filename);
                    const busy = busyDocAction[file.filename];
                    const indexedDoc = indexedDocsMap.get(file.filename);
                    const topicCount = indexedDoc?.topic_count ?? 0;

                    let statusLabel: string;
                    let statusClass: string;
                    let StatusIco: typeof Loader2 | typeof Database | typeof CheckCircle | typeof AlertCircle | typeof Sparkles | typeof Trash2;
                    let spinIcon = false;
                    if (busy === 'extract') {
                      statusLabel = 'Đang trích xuất…';
                      statusClass = 'extracting';
                      StatusIco = Sparkles;
                      spinIcon = true;
                    } else if (busy === 'remove') {
                      statusLabel = 'Đang xóa…';
                      statusClass = 'failed';
                      StatusIco = Trash2;
                      spinIcon = true;
                    } else if (busy === 'index') {
                      statusLabel = 'Đang index…';
                      statusClass = 'indexing';
                      StatusIco = Database;
                      spinIcon = true;
                    } else if (busy === 'edit') {
                      statusLabel = 'Đang mở…';
                      statusClass = 'downloading';
                      StatusIco = Loader2;
                      spinIcon = true;
                    } else if (indexed) {
                      statusLabel = 'Đã index';
                      statusClass = 'indexed';
                      StatusIco = CheckCircle;
                    } else {
                      statusLabel = 'Chưa index';
                      statusClass = 'idle';
                      StatusIco = AlertCircle;
                    }

                    return (
                      <tr key={file.filename}>
                        <td>
                          <div className="file-name" title={file.filename}>
                            <FileText size={16} />
                            <span>{file.filename}</span>
                          </div>
                        </td>
                        <td>
                          <span className="file-size">{formatFileSize(file.size)}</span>
                        </td>
                        <td>
                          {indexed ? (
                            indexedDoc ? (
                              <span className={`topic-count ${topicCount === 0 ? 'empty' : ''}`}>
                                {topicCount > 0 ? `${topicCount} chủ đề` : '— chưa trích xuất'}
                              </span>
                            ) : (
                              // File is known to be indexed (via paginated list)
                              // but the full filename→topic map is still loading.
                              // Show a loader instead of a misleading "chưa trích xuất".
                              <span className="topic-count loading">
                                <Loader2 size={12} className="spin" />
                                Đang tải…
                              </span>
                            )
                          ) : indexedDocsMapLoading ? (
                            <span className="topic-count loading">
                              <Loader2 size={12} className="spin" />
                              Đang tải…
                            </span>
                          ) : (
                            <span className="topic-count empty">—</span>
                          )}
                        </td>
                        <td>
                          <span className={`file-status ${statusClass}`}>
                            <StatusIco size={14} className={spinIcon ? 'spin' : ''} />
                            {statusLabel}
                          </span>
                        </td>
                        <td className="actions-cell">
                          <div className="action-buttons">
                            {indexed ? (
                              <>
                                <button
                                  type="button"
                                  className="btn-action"
                                  onClick={() => handleExtractDocTopics(file.filename)}
                                  disabled={!!busy}
                                  title="Trích xuất lại chủ đề từ nội dung file (chạy LLM)"
                                  aria-label="Trích xuất chủ đề"
                                >
                                  <Sparkles size={15} />
                                </button>
                                <button
                                  type="button"
                                  className="btn-action"
                                  onClick={() => handleEditDocTopics(file.filename)}
                                  disabled={!!busy}
                                  title="Sửa danh sách chủ đề (thêm/sửa/xóa thủ công)"
                                  aria-label="Sửa chủ đề"
                                >
                                  <Edit2 size={15} />
                                </button>
                              </>
                            ) : (
                              <button
                                type="button"
                                className="btn-action btn-primary-action"
                                onClick={() => handleIndexFile(file.filename)}
                                disabled={!!busy}
                                title="Index file này vào cơ sở dữ liệu để có thể tạo quiz / trích xuất chủ đề"
                                aria-label="Index file"
                              >
                                <Database size={15} />
                              </button>
                            )}
                            <button
                              type="button"
                              className="btn-action warning"
                              onClick={() => handleRemoveDocIndex(file.filename)}
                              disabled={!!busy}
                              title="Xóa file PDF + toàn bộ index và chủ đề liên quan (không thể hoàn tác)"
                              aria-label="Xóa file và dữ liệu"
                            >
                              <Trash2 size={15} />
                            </button>
                          </div>
                        </td>
                      </tr>
                    );
                  })}
                </tbody>
              </table>
            </div>
            {uploadedPages > 1 && (
              <div className="pagination pagination--compact">
                <button
                  type="button"
                  className="pagination-btn"
                  disabled={uploadedPage <= 1}
                  onClick={() => { setUploadedPage(p => p - 1); loadUploadedFiles(uploadedPage - 1); }}
                >
                  ‹ Trước
                </button>
                <span className="pagination-info">
                  Trang {uploadedPage} / {uploadedPages}
                </span>
                <button
                  type="button"
                  className="pagination-btn"
                  disabled={uploadedPage >= uploadedPages}
                  onClick={() => { setUploadedPage(p => p + 1); loadUploadedFiles(uploadedPage + 1); }}
                >
                  Sau ›
                </button>
              </div>
            )}
          </div>
        )}
      </div>

      {/* Topic Selector Modal */}
      {showTopicModal && (
        <div className="modal-overlay" onClick={closeTopicModal}>
          <div className="topic-modal" onClick={(e) => e.stopPropagation()}>
            <div className="modal-header">
              <h3>
                <BookOpen size={20} />
                Chọn chủ đề cho Quiz
              </h3>
              <button className="modal-close" onClick={closeTopicModal}>
                <X size={16} />
                <span>Đóng</span>
              </button>
            </div>

            {/* Topic Source Selector */}
            <div className="topic-source-selector">
              <button
                className={`source-tab ${topicSource === 'upload' ? 'active' : ''}`}
                onClick={() => {
                  setTopicSource('upload');
                  setTempSelectedDocuments([]);
                  setTempSelectedTopics([]);
                  setTempTopicsByDocument({});
                }}
              >
                <Upload size={16} />
                File tải lên
                <span className="source-count">{indexedTotal}</span>
              </button>
              <button
                className={`source-tab ${topicSource === 'canvas' ? 'active' : ''}`}
                onClick={() => {
                  setTopicSource('canvas');
                  setTempSelectedDocuments([]);
                  setTempSelectedTopics([]);
                  setTempTopicsByDocument({});
                }}
              >
                <FolderOpen size={16} />
                Canvas LMS
                <span className="source-count">{canvasIndexedDocuments.length}</span>
              </button>
            </div>
            
            <div className="modal-body">
              {/* Selected topics summary */}
              {tempSelectedTopics.length > 0 && (
                <div className="modal-selected-summary">
                  <span className="summary-label">
                    <CheckCircle size={16} />
                    Đã chọn {tempSelectedTopics.length} chủ đề từ {tempSelectedDocuments.length} tài liệu
                    {topicSource === 'canvas' && (() => {
                      const courseIds = new Set(
                        tempSelectedTopics
                          .map(t => getCourseIdFromKey(t.documentFilename))
                          .filter((id): id is number => id != null)
                      );
                      return courseIds.size > 1 ? ` (${courseIds.size} khóa học)` : '';
                    })()}
                  </span>
                </div>
              )}

              {/* Document list */}
              <div className="modal-documents">
                {topicSource === 'upload' ? (
                  /* === UPLOAD TAB: flat list (unchanged) === */
                  indexedDocuments.length === 0 ? (
                    <div className="modal-empty-state">
                      <FileText size={32} />
                      <p>Chưa có tài liệu nào được index. Vui lòng upload và index tài liệu trước.</p>
                    </div>
                  ) : indexedDocuments.map((doc) => {
                    const isDocSelected = tempSelectedDocuments.includes(doc.filename);
                    const docTopics = tempTopicsByDocument[doc.filename] || [];
                    const selectedCount = tempSelectedTopics.filter(t => t.documentFilename === doc.filename).length;
                    const topicStateKey = getTopicStateKey('upload', doc.filename);
                    const isLoadingTopics = !!topicLoadingState[topicStateKey];
                    const topicError = topicErrorState[topicStateKey];
                    
                    return (
                      <div 
                        key={doc.filename} 
                        className={`modal-doc-card ${isDocSelected ? 'expanded' : ''}`}
                      >
                        <div 
                          className="modal-doc-header"
                          onClick={() => toggleDocumentInModal(doc)}
                        >
                          <div className="modal-doc-checkbox">
                            <input 
                              type="checkbox" 
                              checked={isDocSelected} 
                              onChange={() => toggleDocumentInModal(doc)}
                              onClick={(e) => e.stopPropagation()}
                            />
                          </div>
                          <div className="modal-doc-info">
                            <FileText size={18} className="doc-icon" />
                            <div className="modal-doc-details">
                              <span className="modal-doc-name">{doc.original_filename}</span>
                              <span className="modal-doc-meta">{doc.topic_count} chủ đề</span>
                            </div>
                          </div>
                          <div className="modal-doc-status">
                            {selectedCount > 0 && (
                              <span className="modal-selected-badge">{selectedCount} đã chọn</span>
                            )}
                            <span className={`modal-expand-icon ${isDocSelected ? 'expanded' : ''}`}>
                              {isDocSelected ? <ChevronUp size={18} /> : <ChevronDown size={18} />}
                            </span>
                          </div>
                        </div>
                        
                        {isDocSelected && (
                          <div className="modal-doc-topics">
                            {docTopics.length > 0 ? (
                              <>
                                <div className="modal-topics-toolbar">
                                  <button
                                    type="button"
                                    className="btn-modal-select-all"
                                    onClick={() => areAllTopicsSelectedInModal(doc.filename) 
                                      ? deselectAllTopicsInModal(doc.filename)
                                      : selectAllTopicsInModal(doc.filename)
                                    }
                                  >
                                    {areAllTopicsSelectedInModal(doc.filename) ? (
                                      <><X size={14} /> Bỏ chọn tất cả</>
                                    ) : (
                                      <><Check size={14} /> Chọn tất cả</>
                                    )}
                                  </button>
                                  <button
                                    type="button"
                                    className="btn-modal-edit-topics"
                                    onClick={(e) => {
                                      e.stopPropagation();
                                      openEditTopicsModal(doc.filename);
                                    }}
                                  >
                                    <Pencil size={14} /> Sửa chủ đề
                                  </button>
                                </div>
                                <div className="modal-topics-grid">
                                  {docTopics.map((topic, idx) => {
                                    const isSelected = isTopicSelectedInModal(topic.name, doc.filename);
                                    return (
                                      <button
                                        key={idx}
                                        type="button"
                                        className={`modal-topic-tag ${isSelected ? 'selected' : ''}`}
                                        onClick={() => toggleTopicInModal(topic.name, doc.filename)}
                                      >
                                        {isSelected && <Check size={14} className="check-icon" />}
                                        <span>{topic.name}</span>
                                      </button>
                                    );
                                  })}
                                </div>
                              </>
                            ) : isLoadingTopics ? (
                              <div className="modal-loading-topics">
                                <Loader2 size={16} className="spin" />
                                <span>Đang tải chủ đề...</span>
                              </div>
                            ) : (
                              <div className="modal-loading-topics">
                                <AlertCircle size={16} />
                                <span>{topicError || 'Tai lieu nay chua co chu de.'}</span>
                              </div>
                            )}
                          </div>
                        )}
                      </div>
                    );
                  })
                ) : (
                  /* === CANVAS TAB: grouped by course === */
                  canvasIndexedDocuments.length === 0 ? (
                    <div className="modal-empty-state">
                      <FileText size={32} />
                      <p>Chưa có tài liệu Canvas nào được index. Vui lòng vào tab Canvas LMS để tải và index tài liệu.</p>
                    </div>
                  ) : (() => {
                    // Group documents by course_id
                    const grouped: Record<number, IndexedDocument[]> = {};
                    for (const doc of canvasIndexedDocuments) {
                      const cid = doc.course_id ?? 0;
                      if (!grouped[cid]) grouped[cid] = [];
                      grouped[cid].push(doc);
                    }
                    // Sort course IDs by resolved name
                    const sortedCourseIds = Object.keys(grouped)
                      .map(Number)
                      .sort((a, b) => {
                        const nameA = courseNameMap[a] || `Course #${a}`;
                        const nameB = courseNameMap[b] || `Course #${b}`;
                        return nameA.localeCompare(nameB);
                      });

                    return sortedCourseIds.map(courseId => {
                      const courseDocs = grouped[courseId];
                      const courseName = courseNameMap[courseId] || `Course #${courseId}`;
                      const isCollapsed = collapsedCourses.has(courseId);
                      const courseSelectedCount = tempSelectedTopics.filter(t =>
                        courseDocs.some(d => getDocSelectionKey(d) === t.documentFilename)
                      ).length;

                      return (
                        <div key={courseId} className="course-group">
                          <div
                            className="course-group-header"
                            onClick={() => {
                              setCollapsedCourses(prev => {
                                const next = new Set(prev);
                                if (next.has(courseId)) next.delete(courseId);
                                else next.add(courseId);
                                return next;
                              });
                            }}
                          >
                            <span className={`course-expand-icon ${isCollapsed ? '' : 'expanded'}`}>
                              {isCollapsed ? <ChevronDown size={16} /> : <ChevronUp size={16} />}
                            </span>
                            <FolderOpen size={16} className="course-icon" />
                            <span className="course-group-name">{courseName}</span>
                            <span className="course-group-badge">{courseDocs.length} tài liệu</span>
                            {courseSelectedCount > 0 && (
                              <span className="modal-selected-badge">{courseSelectedCount} chủ đề đã chọn</span>
                            )}
                          </div>
                          {!isCollapsed && (
                            <div className="course-group-docs">
                              {courseDocs.map((doc) => {
                                const docKey = getDocSelectionKey(doc);
                                const isDocSelected = tempSelectedDocuments.includes(docKey);
                                const docTopics = tempTopicsByDocument[docKey] || [];
                                const selectedCount = tempSelectedTopics.filter(t => t.documentFilename === docKey).length;
                                const topicStateKey = getTopicStateKey('canvas', doc.filename);
                                const isLoadingTopics = !!topicLoadingState[topicStateKey];
                                const topicError = topicErrorState[topicStateKey];

                                return (
                                  <div 
                                    key={docKey} 
                                    className={`modal-doc-card ${isDocSelected ? 'expanded' : ''}`}
                                  >
                                    <div 
                                      className="modal-doc-header"
                                      onClick={() => toggleDocumentInModal(doc)}
                                    >
                                      <div className="modal-doc-checkbox">
                                        <input 
                                          type="checkbox" 
                                          checked={isDocSelected} 
                                          onChange={() => toggleDocumentInModal(doc)}
                                          onClick={(e) => e.stopPropagation()}
                                        />
                                      </div>
                                      <div className="modal-doc-info">
                                        <FileText size={18} className="doc-icon" />
                                        <div className="modal-doc-details">
                                          <span className="modal-doc-name">{doc.original_filename}</span>
                                          <span className="modal-doc-meta">{doc.topic_count} chủ đề</span>
                                        </div>
                                      </div>
                                      <div className="modal-doc-status">
                                        {selectedCount > 0 && (
                                          <span className="modal-selected-badge">{selectedCount} đã chọn</span>
                                        )}
                                        <span className={`modal-expand-icon ${isDocSelected ? 'expanded' : ''}`}>
                                          {isDocSelected ? <ChevronUp size={18} /> : <ChevronDown size={18} />}
                                        </span>
                                      </div>
                                    </div>
                                    
                                    {isDocSelected && (
                                      <div className="modal-doc-topics">
                                        {docTopics.length > 0 ? (
                                          <>
                                            <div className="modal-topics-toolbar">
                                              <button
                                                type="button"
                                                className="btn-modal-select-all"
                                                onClick={() => areAllTopicsSelectedInModal(docKey) 
                                                  ? deselectAllTopicsInModal(docKey)
                                                  : selectAllTopicsInModal(docKey)
                                                }
                                              >
                                                {areAllTopicsSelectedInModal(docKey) ? (
                                                  <><X size={14} /> Bỏ chọn tất cả</>
                                                ) : (
                                                  <><Check size={14} /> Chọn tất cả</>
                                                )}
                                              </button>
                                              <button
                                                type="button"
                                                className="btn-modal-edit-topics"
                                                onClick={(e) => {
                                                  e.stopPropagation();
                                                  openEditTopicsModal(docKey);
                                                }}
                                              >
                                                <Pencil size={14} /> Sửa chủ đề
                                              </button>
                                            </div>
                                            <div className="modal-topics-grid">
                                              {docTopics.map((topic, idx) => {
                                                const isSelected = isTopicSelectedInModal(topic.name, docKey);
                                                return (
                                                  <button
                                                    key={idx}
                                                    type="button"
                                                    className={`modal-topic-tag ${isSelected ? 'selected' : ''}`}
                                                    onClick={() => toggleTopicInModal(topic.name, docKey)}
                                                  >
                                                    {isSelected && <Check size={14} className="check-icon" />}
                                                    <span>{topic.name}</span>
                                                  </button>
                                                );
                                              })}
                                            </div>
                                          </>
                                        ) : isLoadingTopics ? (
                                          <div className="modal-loading-topics">
                                            <Loader2 size={16} className="spin" />
                                            <span>Đang tải chủ đề...</span>
                                          </div>
                                        ) : (
                                          <div className="modal-loading-topics">
                                            <AlertCircle size={16} />
                                            <span>{topicError || 'Tai lieu nay chua co chu de.'}</span>
                                          </div>
                                        )}
                                      </div>
                                    )}
                                  </div>
                                );
                              })}
                            </div>
                          )}
                        </div>
                      );
                    });
                  })()
                )}
              </div>

              {/* Pagination controls for indexed documents in modal */}
              {topicSource === 'upload' && indexedPages > 1 && (
                <div className="pagination-controls">
                  <button disabled={indexedPage <= 1} onClick={() => loadIndexedDocuments(indexedPage - 1)}>Trước</button>
                  <span>Trang {indexedPage} / {indexedPages}</span>
                  <button disabled={indexedPage >= indexedPages} onClick={() => loadIndexedDocuments(indexedPage + 1)}>Sau</button>
                </div>
              )}
            </div>
            
            <div className="modal-footer">
              <button className="btn btn-secondary" onClick={closeTopicModal}>
                Hủy
              </button>
              <button 
                className="btn btn-primary" 
                onClick={saveTopicSelections}
                disabled={tempSelectedTopics.length === 0}
              >
                <Save size={16} />
                Lưu ({tempSelectedTopics.length} chủ đề)
              </button>
            </div>
          </div>
        </div>
      )}

      {/* Edit Topics Modal */}
      {showEditTopicsModal && (
        <div className="modal-overlay edit-topics-overlay" onClick={closeEditTopicsModal}>
          <div className="edit-topics-modal" onClick={(e) => e.stopPropagation()}>
            <div className="modal-header">
              <h3>
                <Pencil size={20} />
                Sửa chủ đề - {(topicSource === 'upload' 
                  ? indexedDocuments.find(d => d.filename === editingDocumentFilename)?.original_filename 
                  : canvasIndexedDocuments.find(d => d.filename === editingDocumentFilename)?.original_filename
                ) || editingDocumentFilename}
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
                    <Info size={16} />
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
                              <Check size={14} />
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
                  <><Loader2 size={16} className="spin" /> Đang lưu...</>
                ) : (
                  <><Save size={16} /> Lưu thay đổi</>
                )}
              </button>
            </div>
          </div>
        </div>
      )}

      {/* Quiz Modal */}
      {showQuizModal && generatedQuiz.length > 0 && (
        <div className="modal-overlay" onClick={() => setShowQuizModal(false)}>
          <div className="quiz-modal" onClick={(e) => e.stopPropagation()}>
            {/* ── Header ── */}
            <div className="quiz-modal-header">
              <div className="qm-header-left">
                <div className="qm-icon-wrap">
                  <BookOpen size={20} />
                </div>
                <div className="qm-header-text">
                  <h3>
                    {selectedTopics.length > 0
                      ? selectedTopics.map(t => t.topic).slice(0, 2).join(', ') + (selectedTopics.length > 2 ? ` +${selectedTopics.length - 2}` : '')
                      : quizTopic || 'Quiz'}
                  </h3>
                  <div className="qm-header-tags">
                    <span className="qm-chip qm-chip-count">
                      <HelpCircle size={12} /> {generatedQuiz.length} câu
                    </span>
                    <span className="qm-chip qm-chip-difficulty">
                      {quizDifficulty === 'easy' ? '🟢 Dễ' : quizDifficulty === 'hard' ? '🔴 Khó' : '🟡 Trung bình'}
                    </span>
                    <span className="qm-chip qm-chip-lang">
                      {quizLanguage === 'vi' ? '🇻🇳 Tiếng Việt' : '🇬🇧 English'}
                    </span>
                    {topicSource === 'canvas' && (
                      <span className="qm-chip qm-chip-source">Canvas</span>
                    )}
                  </div>
                </div>
              </div>
              <button className="qm-close-btn" onClick={() => setShowQuizModal(false)} aria-label="Đóng">
                <X size={18} />
              </button>
            </div>
            
            {/* ── Body ── */}
            <div className="quiz-modal-body">
              {quizMessage && (
                <div className="qm-alert">
                  <Info size={15} />
                  {quizMessage}
                </div>
              )}

              <div className="quiz-questions">
                {generatedQuiz.map((q, idx) => (
                  <div key={idx} className={`qm-question ${editingQuestionIndex === idx ? 'qm-question-editing' : ''}`}>
                    {/* Question top bar */}
                    <div className="qm-q-header">
                      <span className="qm-q-num">Câu {q.question_number}</span>
                      <div className="qm-q-actions">
                        {editingQuestionIndex === idx ? (
                          <>
                            <button className="qm-action-btn qm-action-cancel" onClick={handleCancelEdit} title="Hủy">
                              <X size={14} /> Hủy
                            </button>
                            <button className="qm-action-btn qm-action-save" onClick={handleSaveQuestion} title="Lưu">
                              <Check size={14} /> Lưu
                            </button>
                          </>
                        ) : (
                          <button
                            className="qm-action-btn qm-action-edit"
                            onClick={() => handleStartEdit(idx)}
                            title="Chỉnh sửa"
                          >
                            <Pencil size={13} /> Sửa
                          </button>
                        )}
                      </div>
                    </div>

                    {/* Question text */}
                    {editingQuestionIndex === idx && editingQuestion ? (
                      <textarea
                        className="qm-edit-textarea"
                        value={editingQuestion.question}
                        onChange={(e) => handleEditQuestion('question', e.target.value)}
                        rows={2}
                        autoFocus
                      />
                    ) : (
                      <p className="qm-q-text">{q.question}</p>
                    )}

                    {/* Options */}
                    <div className="qm-options">
                      {(editingQuestionIndex === idx && editingQuestion
                        ? Object.entries(editingQuestion.options)
                        : Object.entries(q.options)
                      ).map(([key, value]) => {
                        const isCorrect = editingQuestionIndex === idx && editingQuestion
                          ? editingQuestion.correct_answer === key
                          : q.correct_answer === key;
                        const isEditing = editingQuestionIndex === idx && editingQuestion;

                        return (
                          <div
                            key={key}
                            className={`qm-option ${isCorrect ? 'qm-option-correct' : ''} ${isEditing ? 'qm-option-editable' : ''}`}
                          >
                            <span className={`qm-option-letter ${isCorrect ? 'qm-letter-correct' : ''}`}>
                              {key}
                            </span>
                            {isEditing ? (
                              <input
                                type="text"
                                className="qm-option-input"
                                value={value}
                                onChange={(e) => handleEditQuestion('option', [key, e.target.value])}
                              />
                            ) : (
                              <span className="qm-option-text">{value}</span>
                            )}
                            {isEditing ? (
                              <label className="qm-radio-label" title="Đáp án đúng">
                                <input
                                  type="radio"
                                  name={`correct-${idx}`}
                                  checked={isCorrect}
                                  onChange={() => handleEditQuestion('correct_answer', key)}
                                />
                                <span className={`qm-radio-dot ${isCorrect ? 'qm-radio-active' : ''}`} />
                              </label>
                            ) : (
                              isCorrect && <CheckCircle size={16} className="qm-correct-icon" />
                            )}
                          </div>
                        );
                      })}
                    </div>
                  </div>
                ))}
              </div>
            </div>
            
            {/* ── Footer ── */}
            <div className="quiz-modal-footer">
              <div className="qm-footer-left">
                <button className="qm-footer-btn qm-btn-close" onClick={() => setShowQuizModal(false)}>
                  Đóng
                </button>
              </div>
              <div className="qm-footer-right">
                <button
                  className="qm-footer-btn qm-btn-download"
                  onClick={handleDownloadQTI}
                  disabled={isExporting || editingQuestionIndex !== null}
                  title="Download QTI ZIP"
                >
                  <Download size={15} /> Download
                </button>
                <button
                  className="qm-footer-btn qm-btn-export"
                  onClick={handleExportQTI}
                  disabled={isExporting || editingQuestionIndex !== null}
                >
                  {isExporting ? (
                    <><Loader2 size={15} className="spin" /> Đang chuẩn bị…</>
                  ) : (
                    <><Upload size={15} /> Export Canvas</>
                  )}
                </button>
                {onDeployToCanvas && (
                  <button
                    className="qm-footer-btn qm-btn-deploy"
                    onClick={() => { onDeployToCanvas(generatedQuiz); setShowQuizModal(false); }}
                    disabled={generatedQuiz.length === 0}
                  >
                    <Rocket size={15} /> Quiz Builder
                  </button>
                )}
                <button
                  className={`qm-footer-btn qm-btn-save ${saveLibrarySuccess ? 'qm-btn-save-ok' : ''}`}
                  onClick={openSaveQuizModal}
                  disabled={generatedQuiz.length === 0 || isSavingToLibrary}
                  title="Lưu vào Kho Đề Thi"
                >
                  {isSavingToLibrary ? (
                    <><Loader2 size={15} className="spin" /> Đang lưu…</>
                  ) : saveLibrarySuccess ? (
                    <><Check size={15} /> Đã lưu!</>
                  ) : (
                    <><Library size={15} /> Lưu Kho Đề</>
                  )}
                </button>
              </div>
            </div>
          </div>
        </div>
      )}

      {/* Canvas Import Modal */}
      <CanvasImportModal
        isOpen={showCanvasImportModal}
        onClose={() => {
          setShowCanvasImportModal(false);
          setQtiZipBlob(null);
        }}
        qtiZipBlob={qtiZipBlob}
        defaultBankName={`AI-TA Bank - ${quizTopic || new Date().toLocaleDateString()}`}
        onNavigateToQuizBuilder={onDeployToCanvas ? () => {
          onDeployToCanvas(generatedQuiz);
        } : undefined}
      />

      {/* Save-to-Kho-Đề Modal (V2) */}
      {showSaveQuizModal && (
        <div
          className="sqm-overlay"
          onClick={(e) => {
            if (e.target === e.currentTarget && !isSavingToLibrary) {
              setShowSaveQuizModal(false);
            }
          }}
        >
          <div className="sqm-modal" role="dialog" aria-modal="true" aria-labelledby="sqm-title">
            <div className="sqm-header">
              <div className="sqm-header-icon">
                <Library size={20} />
              </div>
              <div className="sqm-header-text">
                <h3 id="sqm-title" className="sqm-title">Lưu vào Kho Đề Thi</h3>
                <p className="sqm-subtitle">
                  {generatedQuiz.length} câu hỏi · {quizDifficulty === 'easy' ? 'Dễ' : quizDifficulty === 'medium' ? 'Trung bình' : 'Khó'} · {quizLanguage === 'vi' ? 'Tiếng Việt' : 'English'}
                </p>
              </div>
              <button
                className="sqm-close"
                onClick={() => !isSavingToLibrary && setShowSaveQuizModal(false)}
                disabled={isSavingToLibrary}
                aria-label="Đóng"
              >
                <X size={18} />
              </button>
            </div>

            <div className="sqm-body">
              <div className="sqm-field">
                <label className="sqm-label" htmlFor="sqm-input-title">
                  Tên quiz <span className="sqm-required">*</span>
                </label>
                <input
                  id="sqm-input-title"
                  type="text"
                  className="sqm-input"
                  value={saveQuizTitle}
                  onChange={(e) => setSaveQuizTitle(e.target.value)}
                  placeholder="VD: Đề ôn tập chương 1 — Tương tác người máy"
                  maxLength={200}
                  autoFocus
                  disabled={isSavingToLibrary}
                  onKeyDown={(e) => {
                    if (e.key === 'Enter' && !e.shiftKey) {
                      e.preventDefault();
                      confirmSaveQuiz();
                    } else if (e.key === 'Escape' && !isSavingToLibrary) {
                      setShowSaveQuizModal(false);
                    }
                  }}
                />
                <div className="sqm-hint">{saveQuizTitle.length} / 200 ký tự</div>
              </div>

              <div className="sqm-field">
                <label className="sqm-label" htmlFor="sqm-input-desc">
                  Mô tả <span className="sqm-optional">(tùy chọn)</span>
                </label>
                <textarea
                  id="sqm-input-desc"
                  className="sqm-textarea"
                  value={saveQuizDescription}
                  onChange={(e) => setSaveQuizDescription(e.target.value)}
                  placeholder="Mô tả ngắn gọn về quiz này, đối tượng học viên, mục tiêu kiểm tra…"
                  rows={3}
                  maxLength={500}
                  disabled={isSavingToLibrary}
                />
                <div className="sqm-hint">{saveQuizDescription.length} / 500 ký tự</div>
              </div>

              <div className="sqm-field">
                <label className="sqm-label" htmlFor="sqm-input-tags">
                  Tags <span className="sqm-optional">(phân cách bằng dấu phẩy)</span>
                </label>
                <input
                  id="sqm-input-tags"
                  type="text"
                  className="sqm-input"
                  value={saveQuizTagsInput}
                  onChange={(e) => setSaveQuizTagsInput(e.target.value)}
                  placeholder="VD: chương 1, ôn tập, giữa kỳ"
                  disabled={isSavingToLibrary}
                />
                {saveQuizTagsInput.trim() && (
                  <div className="sqm-tag-preview">
                    {saveQuizTagsInput.split(',').map(t => t.trim()).filter(Boolean).map((tag, i) => (
                      <span key={i} className="sqm-tag-chip">{tag}</span>
                    ))}
                  </div>
                )}
              </div>

              {saveQuizError && (
                <div className="sqm-error" role="alert">
                  <AlertCircle size={14} />
                  <span>{saveQuizError}</span>
                </div>
              )}
            </div>

            <div className="sqm-footer">
              <button
                className="sqm-btn sqm-btn-secondary"
                onClick={() => setShowSaveQuizModal(false)}
                disabled={isSavingToLibrary}
              >
                Hủy
              </button>
              <button
                className="sqm-btn sqm-btn-primary"
                onClick={confirmSaveQuiz}
                disabled={isSavingToLibrary || !saveQuizTitle.trim()}
                aria-disabled={isSavingToLibrary || !saveQuizTitle.trim()}
                title={
                  isSavingToLibrary
                    ? 'Đang lưu, vui lòng đợi...'
                    : !saveQuizTitle.trim()
                      ? 'Hãy nhập tiêu đề cho quiz trước'
                      : 'Lưu quiz vào Kho Đề'
                }
              >
                {isSavingToLibrary ? (
                  <><Loader2 size={15} className="spin" /> Đang lưu…</>
                ) : (
                  <><Save size={15} /> Lưu vào Kho Đề</>
                )}
              </button>
            </div>
          </div>
        </div>
      )}

      <style>{`
        /* ===================================================================
           DOCUMENT RAG PANEL — PREMIUM DARK THEME
           Matching Chat AI Panel aesthetics with vibrant accent colors
        =================================================================== */

        .document-rag-panel {
          display: flex;
          flex-direction: column;
          height: 100%;
          overflow: hidden;
          background: #080b18;
          border-radius: 0;
          box-shadow: none;
          position: relative;
        }

        /* Ambient gradient layer */
        .document-rag-panel::before {
          content: '';
          position: absolute;
          inset: 0;
          background:
            radial-gradient(ellipse 80% 60% at 20% 10%, rgba(56, 189, 248, 0.10) 0%, transparent 60%),
            radial-gradient(ellipse 60% 50% at 80% 90%, rgba(139, 92, 246, 0.08) 0%, transparent 60%),
            radial-gradient(ellipse 50% 40% at 50% 50%, rgba(6, 182, 212, 0.05) 0%, transparent 60%);
          pointer-events: none;
          z-index: 0;
        }

        /* Grid overlay */
        .document-rag-panel::after {
          content: '';
          position: absolute;
          inset: 0;
          background-image:
            linear-gradient(rgba(56, 189, 248, 0.02) 1px, transparent 1px),
            linear-gradient(90deg, rgba(56, 189, 248, 0.02) 1px, transparent 1px);
          background-size: 50px 50px;
          mask-image: radial-gradient(ellipse 80% 70% at 50% 50%, black 20%, transparent 75%);
          -webkit-mask-image: radial-gradient(ellipse 80% 70% at 50% 50%, black 20%, transparent 75%);
          pointer-events: none;
          animation: rag-grid-drift 30s linear infinite;
          z-index: 0;
        }

        @keyframes rag-grid-drift {
          0% { transform: translate(0, 0); }
          100% { transform: translate(50px, 50px); }
        }

        /* Decorative floating orbs */
        .rag-bg-decoration {
          position: absolute;
          inset: 0;
          pointer-events: none;
          overflow: hidden;
          z-index: 0;
        }

        .rag-bg-orb {
          position: absolute;
          border-radius: 50%;
          filter: blur(70px);
        }

        .rag-bg-orb-1 {
          width: 350px;
          height: 350px;
          background: radial-gradient(circle, rgba(56, 189, 248, 0.13) 0%, rgba(56, 189, 248, 0) 70%);
          top: -12%;
          right: -6%;
          animation: rag-orb-1 22s ease-in-out infinite;
        }

        .rag-bg-orb-2 {
          width: 300px;
          height: 300px;
          background: radial-gradient(circle, rgba(139, 92, 246, 0.10) 0%, rgba(139, 92, 246, 0) 70%);
          bottom: 3%;
          left: -10%;
          animation: rag-orb-2 26s ease-in-out infinite;
        }

        .rag-bg-orb-3 {
          width: 220px;
          height: 220px;
          background: radial-gradient(circle, rgba(34, 211, 238, 0.07) 0%, rgba(34, 211, 238, 0) 70%);
          top: 45%;
          left: 55%;
          animation: rag-orb-3 18s ease-in-out infinite;
        }

        @keyframes rag-orb-1 {
          0%, 100% { transform: translate(0, 0) scale(1); }
          25% { transform: translate(30px, 20px) scale(1.08); }
          50% { transform: translate(-15px, 40px) scale(0.95); }
          75% { transform: translate(20px, -15px) scale(1.03); }
        }

        @keyframes rag-orb-2 {
          0%, 100% { transform: translate(0, 0) scale(1); }
          25% { transform: translate(-25px, -30px) scale(1.05); }
          50% { transform: translate(30px, -15px) scale(0.97); }
          75% { transform: translate(-15px, 25px) scale(1.04); }
        }

        @keyframes rag-orb-3 {
          0%, 100% { transform: translate(0, 0) scale(1); }
          33% { transform: translate(20px, -25px) scale(1.1); }
          66% { transform: translate(-22px, 18px) scale(0.9); }
        }

        /* Twinkling stars */
        .rag-stars {
          position: absolute;
          inset: 0;
          pointer-events: none;
          overflow: hidden;
          z-index: 0;
        }

        .rag-star {
          position: absolute;
          background: #ffffff;
          border-radius: 50%;
          animation: rag-twinkle var(--duration, 4s) ease-in-out infinite;
          animation-delay: var(--delay, 0s);
          opacity: 0;
        }

        .rag-star::after {
          content: '';
          position: absolute;
          inset: -1px;
          background: inherit;
          border-radius: 50%;
          box-shadow: 0 0 6px 1px rgba(255, 255, 255, 0.35);
        }

        @keyframes rag-twinkle {
          0%, 100% { opacity: 0; transform: scale(0.5); }
          50% { opacity: 0.85; transform: scale(1.3); }
        }

        /* Glowing line accents */
        .rag-glow-line {
          position: absolute;
          pointer-events: none;
          overflow: hidden;
          z-index: 0;
        }

        .rag-glow-line-1 {
          top: 18%;
          left: 0;
          width: 45%;
          height: 1px;
          background: linear-gradient(90deg, transparent 0%, rgba(56, 189, 248, 0.30) 50%, transparent 100%);
          animation: rag-line-slide 8s ease-in-out infinite;
        }

        .rag-glow-line-2 {
          bottom: 25%;
          right: 0;
          width: 38%;
          height: 1px;
          background: linear-gradient(90deg, transparent 0%, rgba(167, 139, 250, 0.22) 50%, transparent 100%);
          animation: rag-line-slide 10s ease-in-out infinite reverse;
        }

        @keyframes rag-line-slide {
          0%, 100% { transform: translateX(-20px); opacity: 0.3; }
          50% { transform: translateX(20px); opacity: 1; }
        }

        /* ===== HERO HEADER ===== */
        .rag-hero-header {
          display: flex;
          align-items: center;
          gap: 16px;
          padding: 20px 28px;
          background: rgba(15, 23, 42, 0.85);
          backdrop-filter: blur(16px);
          -webkit-backdrop-filter: blur(16px);
          border-bottom: 1px solid rgba(56, 189, 248, 0.2);
          flex-shrink: 0;
          position: relative;
          z-index: 3;
          box-shadow: 0 4px 20px rgba(0, 0, 0, 0.3), inset 0 1px 0 rgba(255, 255, 255, 0.05);
        }

        .rag-hero-header::after {
          content: '';
          position: absolute;
          bottom: -1px;
          left: 5%;
          width: 90%;
          height: 1px;
          background: linear-gradient(90deg, transparent, rgba(56, 189, 248, 0.4), rgba(139, 92, 246, 0.3), rgba(34, 211, 238, 0.2), transparent);
        }

        .rag-hero-icon {
          display: flex;
          align-items: center;
          justify-content: center;
          width: 48px;
          height: 48px;
          background: linear-gradient(135deg, #38bdf8 0%, #0ea5e9 100%);
          border-radius: 14px;
          color: white;
          box-shadow: 0 6px 20px -4px rgba(56, 189, 248, 0.5);
          flex-shrink: 0;
          position: relative;
          transition: all 0.35s cubic-bezier(0.34, 1.56, 0.64, 1);
        }

        .rag-hero-icon::after {
          content: '';
          position: absolute;
          inset: -4px;
          border-radius: 18px;
          border: 1.5px dashed rgba(56, 189, 248, 0.35);
          animation: rag-icon-orbit 12s linear infinite;
        }

        @keyframes rag-icon-orbit {
          from { transform: rotate(0deg); }
          to { transform: rotate(360deg); }
        }

        .rag-hero-icon:hover {
          transform: scale(1.08) rotate(-5deg);
          box-shadow:
            0 10px 28px -4px rgba(56, 189, 248, 0.6),
            0 0 0 4px rgba(56, 189, 248, 0.12);
        }

        .rag-hero-text {
          flex-shrink: 0;
        }

        .rag-hero-text h2 {
          margin: 0;
          font-size: 1.3rem;
          font-weight: 700;
          background: linear-gradient(135deg, #e0f2fe 0%, #bae6fd 40%, #7dd3fc 80%, #38bdf8 100%);
          background-clip: text;
          -webkit-background-clip: text;
          -webkit-text-fill-color: transparent;
          letter-spacing: -0.01em;
        }

        .rag-hero-text p {
          margin: 4px 0 0 0;
          font-size: 0.85rem;
          color: #94a3b8;
          font-weight: 400;
        }

        /* ===== HEADER CHIPS (provider + model) ===== */
        .rag-header-chips {
          display: flex;
          align-items: center;
          gap: 6px;
          margin-left: auto;
          flex-shrink: 0;
        }

        .rag-chip {
          display: flex;
          align-items: center;
          gap: 5px;
          padding: 5px 10px;
          border-radius: 8px;
          font-size: 0.78rem;
          font-weight: 500;
          white-space: nowrap;
          transition: all 0.2s ease;
        }

        .rag-chip-provider {
          background: rgba(139, 92, 246, 0.1);
          border: 1px solid rgba(139, 92, 246, 0.25);
          color: #c4b5fd;
        }
        .rag-chip-provider svg { color: #a78bfa; }

        .rag-chip-model {
          border: 1px solid rgba(56, 189, 248, 0.2);
        }
        .rag-chip-model.connected {
          background: rgba(52, 211, 153, 0.08);
          border-color: rgba(52, 211, 153, 0.25);
          color: #6ee7b7;
        }
        .rag-chip-model.disconnected {
          background: rgba(248, 113, 113, 0.08);
          border-color: rgba(248, 113, 113, 0.2);
          color: #fca5a5;
        }

        .rag-chip-status-icon {
          flex-shrink: 0;
        }
        .rag-chip-model.connected .rag-chip-status-icon { color: #34d399; }
        .rag-chip-model.disconnected .rag-chip-status-icon { color: #f87171; }

        .rag-chip-model-name {
          font-family: 'Consolas', 'Monaco', monospace;
          font-size: 0.75rem;
          font-weight: 600;
          color: #7dd3fc;
        }

        .rag-chip-text {
          font-weight: 500;
        }
        .rag-chip-text.disconnected {
          color: #fca5a5;
        }

        .rag-chip-divider {
          width: 1px;
          height: 18px;
          background: rgba(56, 189, 248, 0.12);
          flex-shrink: 0;
        }

        .btn-hero-refresh {
          display: flex;
          align-items: center;
          justify-content: center;
          width: 40px;
          height: 40px;
          background: rgba(15, 23, 42, 0.6);
          border: 1px solid rgba(56, 189, 248, 0.2);
          border-radius: 10px;
          color: #38bdf8;
          cursor: pointer;
          transition: all 0.3s ease;
          flex-shrink: 0;
        }

        .btn-hero-refresh:hover {
          background: rgba(56, 189, 248, 0.15);
          border-color: rgba(56, 189, 248, 0.4);
          color: #38bdf8;
          transform: rotate(180deg);
          box-shadow: 0 0 12px rgba(56, 189, 248, 0.2);
        }

        /* ===== CONTENT AREA ===== */
        .rag-content {
          flex: 1;
          overflow-y: auto;
          padding: 24px;
          display: flex;
          flex-direction: column;
          gap: 20px;
          background: transparent;
          position: relative;
          z-index: 2;
        }

        .rag-content::-webkit-scrollbar {
          width: 8px;
        }

        .rag-content::-webkit-scrollbar-track {
          background: transparent;
        }

        .rag-content::-webkit-scrollbar-thumb {
          background: rgba(56, 189, 248, 0.2);
          border-radius: 10px;
        }

        .rag-content::-webkit-scrollbar-thumb:hover {
          background: rgba(56, 189, 248, 0.35);
        }

        /* ===== LEGACY STATUS (kept for message compat) ===== */

        .provider-dropdown-inline {
          padding: 3px 22px 3px 6px;
          border: 1px solid rgba(139, 92, 246, 0.35);
          border-radius: 6px;
          background: rgba(22, 33, 55, 0.85);
          color: #e2e8f0;
          font-size: 0.78rem;
          font-weight: 500;
          cursor: pointer;
          transition: all 0.2s ease;
          appearance: none;
          background-image: url("data:image/svg+xml,%3Csvg xmlns='http://www.w3.org/2000/svg' width='12' height='12' viewBox='0 0 24 24' fill='none' stroke='%2394a3b8' stroke-width='2' stroke-linecap='round' stroke-linejoin='round'%3E%3Cpolyline points='6 9 12 15 18 9'%3E%3C/polyline%3E%3C/svg%3E");
          background-repeat: no-repeat;
          background-position: right 6px center;
          background-size: 10px;
        }

        .provider-dropdown-inline:hover:not(:disabled) {
          border-color: #a78bfa;
          background-color: rgba(139, 92, 246, 0.12);
        }

        .provider-dropdown-inline:focus {
          outline: none;
          border-color: #a78bfa;
          box-shadow: 0 0 0 2px rgba(139, 92, 246, 0.15);
        }

        .provider-dropdown-inline:disabled {
          opacity: 0.6;
          cursor: not-allowed;
        }

        .provider-dropdown-inline option {
          background: #0f172a;
          color: #e2e8f0;
        }

        .provider-dropdown-inline option:disabled {
          color: #64748b;
        }

        .model-name-inline {
          font-family: 'Consolas', 'Monaco', monospace;
          font-size: 0.8rem;
          background: rgba(56, 189, 248, 0.1);
          padding: 2px 8px;
          border-radius: 5px;
          color: #7dd3fc;
          font-weight: 600;
          border: 1px solid rgba(56, 189, 248, 0.2);
        }

        .status-text-inline {
          color: #f87171;
          font-weight: 500;
          font-size: 0.82rem;
        }

        /* ===== UPLOAD SECTION REDESIGN ===== */
        .upload-section-redesign {
          /* Remove old grid, just full width */
        }

        .status-icon.success {
          color: #34d399;
        }

        .status-icon.error {
          color: #f87171;
        }

        .provider-dropdown-wrapper {
          position: relative;
        }

        .provider-dropdown-loading {
          position: absolute;
          right: 6px;
          top: 50%;
          transform: translateY(-50%);
          color: #a78bfa;
        }

        /* ===== UPLOAD SECTION ===== */
        .upload-section-compact {
          background: rgba(22, 33, 55, 0.8);
          backdrop-filter: blur(12px);
          border: 1px solid rgba(56, 189, 248, 0.2);
          border-radius: 16px;
          padding: 24px;
          box-shadow: 0 4px 24px rgba(0, 0, 0, 0.35), inset 0 1px 0 rgba(255, 255, 255, 0.05), 0 0 0 1px rgba(56, 189, 248, 0.06);
          transition: all 0.3s ease;
          display: flex;
          flex-direction: column;
        }

        .upload-section-compact:hover {
          box-shadow: 0 8px 32px rgba(56, 189, 248, 0.12), inset 0 1px 0 rgba(255, 255, 255, 0.06), 0 0 0 1px rgba(56, 189, 248, 0.1);
          border-color: rgba(56, 189, 248, 0.35);
        }

        .upload-section-compact h3 {
          display: flex;
          align-items: center;
          gap: 10px;
          margin: 0 0 16px 0;
          font-size: 1.05rem;
          font-weight: 700;
          color: #f1f5f9;
          padding-bottom: 12px;
          border-bottom: 1px solid rgba(56, 189, 248, 0.18);
        }

        .upload-section-compact h3 svg {
          color: #38bdf8;
        }

        .files-count-badge {
          margin-left: auto;
          background: linear-gradient(135deg, #38bdf8 0%, #0ea5e9 100%);
          color: white;
          padding: 4px 10px;
          border-radius: 20px;
          font-size: 0.75rem;
          font-weight: 600;
          box-shadow: 0 2px 8px rgba(56, 189, 248, 0.3);
        }

        .upload-area-compact {
          flex: 1;
          margin-bottom: 16px;
        }

        .file-label-compact {
          display: flex;
          align-items: center;
          gap: 16px;
          padding: 20px;
          border: 2px dashed rgba(56, 189, 248, 0.3);
          border-radius: 14px;
          cursor: pointer;
          transition: all 0.3s ease;
          background: rgba(22, 33, 55, 0.6);
          min-height: 90px;
          position: relative;
        }

        .file-label-compact:hover {
          border-color: #38bdf8;
          background: rgba(56, 189, 248, 0.06);
          transform: translateY(-1px);
          box-shadow: 0 6px 20px rgba(56, 189, 248, 0.1);
        }

        .file-label-compact.has-file {
          border-style: solid;
          border-color: #34d399;
          background: rgba(34, 211, 153, 0.06);
        }

        .file-label-compact.has-file:hover {
          border-color: #10b981;
          background: rgba(34, 211, 153, 0.1);
        }

        .upload-icon-wrapper {
          display: flex;
          align-items: center;
          justify-content: center;
          width: 52px;
          height: 52px;
          background: linear-gradient(135deg, #38bdf8 0%, #0ea5e9 100%);
          border-radius: 14px;
          color: white;
          flex-shrink: 0;
          transition: all 0.3s ease;
          box-shadow: 0 3px 10px rgba(56, 189, 248, 0.25);
        }

        .file-label-compact.has-file .upload-icon-wrapper {
          background: linear-gradient(135deg, #34d399 0%, #10b981 100%);
          box-shadow: 0 4px 12px rgba(52, 211, 153, 0.3);
        }

        .file-label-compact:hover .upload-icon-wrapper {
          transform: scale(1.08);
          box-shadow: 0 6px 20px rgba(56, 189, 248, 0.4);
        }

        .file-label-compact.has-file:hover .upload-icon-wrapper {
          box-shadow: 0 6px 20px rgba(52, 211, 153, 0.4);
        }

        .upload-text {
          display: flex;
          flex-direction: column;
          gap: 6px;
          flex: 1;
          min-width: 0;
        }

        .upload-main-text {
          font-size: 1rem;
          font-weight: 600;
          color: #e2e8f0;
          white-space: nowrap;
          overflow: hidden;
          text-overflow: ellipsis;
        }

        .file-label-compact.has-file .upload-main-text {
          color: #34d399;
        }

        .upload-hint {
          display: flex;
          align-items: center;
          gap: 6px;
          font-size: 0.85rem;
          color: #94a3b8;
        }

        .upload-hint svg {
          color: #64748b;
        }

        .file-meta {
          display: flex;
          align-items: center;
          gap: 10px;
        }

        .file-size {
          font-size: 0.8rem;
          color: #34d399;
          background: rgba(52, 211, 153, 0.1);
          padding: 3px 10px;
          border-radius: 20px;
          font-weight: 500;
          border: 1px solid rgba(52, 211, 153, 0.2);
        }

        .file-type {
          font-size: 0.8rem;
          color: #94a3b8;
          background: rgba(100, 116, 139, 0.15);
          padding: 3px 10px;
          border-radius: 20px;
          font-weight: 500;
        }

        .btn-clear-file {
          position: absolute;
          top: 12px;
          right: 12px;
          width: 28px;
          height: 28px;
          display: flex;
          align-items: center;
          justify-content: center;
          border: none;
          background: rgba(239, 68, 68, 0.1);
          color: #f87171;
          border-radius: 50%;
          cursor: pointer;
          transition: all 0.2s ease;
          opacity: 0;
        }

        .file-label-compact:hover .btn-clear-file {
          opacity: 1;
        }

        .btn-clear-file:hover {
          background: #ef4444;
          color: white;
          transform: scale(1.1);
        }

        .upload-actions-compact {
          display: flex;
          gap: 12px;
        }

        .btn-upload-main {
          flex: 1;
          padding: 12px 20px;
          font-size: 0.95rem;
          justify-content: center;
        }

        .btn-outline-danger {
          background: rgba(22, 33, 55, 0.75);
          color: #f87171;
          border: 2px solid rgba(248, 113, 113, 0.35);
          transition: all 0.2s ease;
        }

        .btn-outline-danger:hover:not(:disabled) {
          background: rgba(220, 38, 38, 0.15);
          border-color: #f87171;
          box-shadow: 0 0 16px rgba(248, 113, 113, 0.2);
        }

        .btn-outline-danger:disabled {
          opacity: 0.5;
          color: #475569;
          border-color: rgba(71, 85, 105, 0.3);
        }

        .btn-reset {
          padding: 12px 16px;
        }

        /* Multi-file upload queue styles */
        .btn-add-more {
          display: flex;
          align-items: center;
          gap: 6px;
          padding: 8px 14px;
          background: rgba(22, 33, 55, 0.75);
          border: 2px solid rgba(56, 189, 248, 0.35);
          border-radius: 8px;
          color: #38bdf8;
          font-size: 0.85rem;
          font-weight: 600;
          cursor: pointer;
          transition: all 0.2s ease;
          flex-shrink: 0;
        }

        .btn-add-more:hover {
          background: rgba(56, 189, 248, 0.15);
          border-color: #38bdf8;
          box-shadow: 0 0 16px rgba(56, 189, 248, 0.2);
        }

        .file-label-compact.disabled {
          pointer-events: none;
          opacity: 0.7;
        }

        .files-queue {
          margin-bottom: 16px;
          background: rgba(22, 33, 55, 0.6);
          border: 1px solid rgba(56, 189, 248, 0.15);
          border-radius: 12px;
          padding: 12px;
        }

        .files-queue-header {
          display: flex;
          align-items: center;
          justify-content: space-between;
          margin-bottom: 12px;
          padding-bottom: 10px;
          border-bottom: 1px solid rgba(56, 189, 248, 0.15);
        }

        .queue-title {
          display: flex;
          align-items: center;
          gap: 8px;
          font-size: 0.9rem;
          font-weight: 600;
          color: #e2e8f0;
        }

        .queue-title svg {
          color: #64748b;
        }

        .btn-clear-all-files {
          display: flex;
          align-items: center;
          gap: 6px;
          padding: 6px 12px;
          background: transparent;
          border: 1px solid rgba(248, 113, 113, 0.3);
          border-radius: 6px;
          color: #f87171;
          font-size: 0.8rem;
          font-weight: 500;
          cursor: pointer;
          transition: all 0.2s ease;
        }

        .btn-clear-all-files:hover {
          background: rgba(220, 38, 38, 0.1);
          border-color: #f87171;
        }

        .files-list {
          display: flex;
          flex-direction: column;
          gap: 8px;
          max-height: 200px;
          overflow-y: auto;
          padding-right: 4px;
        }

        .files-list::-webkit-scrollbar {
          width: 6px;
        }

        .files-list::-webkit-scrollbar-track {
          background: rgba(15, 23, 42, 0.3);
          border-radius: 10px;
        }

        .files-list::-webkit-scrollbar-thumb {
          background: rgba(56, 189, 248, 0.2);
          border-radius: 10px;
        }

        .file-queue-item {
          display: flex;
          align-items: center;
          gap: 12px;
          padding: 10px 12px;
          background: rgba(22, 33, 55, 0.6);
          border: 1px solid rgba(56, 189, 248, 0.14);
          border-radius: 10px;
          transition: all 0.3s ease;
        }

        .file-queue-item.status-waiting {
          border-color: rgba(100, 116, 139, 0.2);
        }

        .file-queue-item.status-uploading {
          border-color: rgba(56, 189, 248, 0.4);
          background: rgba(56, 189, 248, 0.06);
          box-shadow: 0 2px 8px rgba(56, 189, 248, 0.1);
        }

        .file-queue-item.status-success {
          border-color: rgba(52, 211, 153, 0.4);
          background: rgba(52, 211, 153, 0.06);
        }

        .file-queue-item.status-error {
          border-color: rgba(248, 113, 113, 0.4);
          background: rgba(248, 113, 113, 0.06);
        }

        .file-queue-item.status-already_indexed {
          border-color: rgba(167, 139, 250, 0.4);
          background: rgba(167, 139, 250, 0.06);
        }

        .file-queue-icon {
          display: flex;
          align-items: center;
          justify-content: center;
          width: 36px;
          height: 36px;
          border-radius: 8px;
          flex-shrink: 0;
        }

        .status-waiting .file-queue-icon {
          background: rgba(100, 116, 139, 0.15);
          color: #94a3b8;
        }

        .status-uploading .file-queue-icon {
          background: rgba(56, 189, 248, 0.15);
          color: #38bdf8;
        }

        .status-success .file-queue-icon {
          background: rgba(52, 211, 153, 0.15);
          color: #34d399;
        }

        .status-error .file-queue-icon {
          background: rgba(248, 113, 113, 0.15);
          color: #f87171;
        }

        .status-already_indexed .file-queue-icon {
          background: rgba(167, 139, 250, 0.15);
          color: #a78bfa;
        }

        .file-queue-info {
          flex: 1;
          min-width: 0;
          display: flex;
          flex-direction: column;
          gap: 2px;
        }

        .file-queue-name {
          font-size: 0.9rem;
          font-weight: 600;
          color: #e2e8f0;
          white-space: nowrap;
          overflow: hidden;
          text-overflow: ellipsis;
        }

        .file-queue-meta {
          display: flex;
          align-items: center;
          gap: 10px;
        }

        .file-queue-size {
          font-size: 0.75rem;
          color: #94a3b8;
          background: rgba(100, 116, 139, 0.12);
          padding: 2px 8px;
          border-radius: 4px;
        }

        .file-queue-status {
          font-size: 0.75rem;
          font-weight: 500;
          padding: 2px 8px;
          border-radius: 4px;
        }

        .file-queue-status.waiting {
          background: rgba(100, 116, 139, 0.12);
          color: #94a3b8;
        }

        .file-queue-status.uploading {
          background: rgba(56, 189, 248, 0.12);
          color: #38bdf8;
        }

        .file-queue-status.success {
          background: rgba(52, 211, 153, 0.12);
          color: #34d399;
        }

        .file-queue-status.error {
          background: rgba(248, 113, 113, 0.12);
          color: #f87171;
        }

        .file-queue-status.already-indexed {
          background: rgba(167, 139, 250, 0.12);
          color: #a78bfa;
        }

        .btn-remove-file {
          display: flex;
          align-items: center;
          justify-content: center;
          width: 28px;
          height: 28px;
          background: transparent;
          border: 1px solid rgba(100, 116, 139, 0.2);
          border-radius: 6px;
          color: #64748b;
          cursor: pointer;
          transition: all 0.2s ease;
          flex-shrink: 0;
        }

        .btn-remove-file:hover {
          background: rgba(220, 38, 38, 0.1);
          border-color: rgba(248, 113, 113, 0.4);
          color: #f87171;
        }

        .upload-progress-summary {
          margin-top: 12px;
          padding-top: 12px;
          border-top: 1px solid rgba(56, 189, 248, 0.08);
        }

        .progress-bar {
          width: 100%;
          height: 8px;
          background: rgba(15, 23, 42, 0.5);
          border-radius: 10px;
          overflow: hidden;
          margin-bottom: 8px;
        }

        .progress-fill {
          height: 100%;
          background: linear-gradient(90deg, #34d399 0%, #10b981 100%);
          border-radius: 10px;
          transition: width 0.5s ease;
          box-shadow: 0 0 8px rgba(52, 211, 153, 0.4);
        }

        .progress-text {
          font-size: 0.8rem;
          font-weight: 500;
          color: #94a3b8;
          text-align: center;
          display: block;
        }

        .message-compact {
          margin-top: 12px;
          padding: 12px 16px;
          font-size: 0.85rem;
          border-radius: 10px;
        }

        .file-input {
          display: none;
        }

        /* Status Section - Remove old styles */
        .status-section {
          display: none;
        }

        /* Upload Section - Hide old styles */
        .upload-section {
          display: none;
        }

        .refresh-btn {
          display: none;
        }

        /* Buttons */
        .btn {
          display: inline-flex;
          align-items: center;
          gap: 8px;
          padding: 10px 16px;
          font-size: 0.875rem;
          font-weight: 500;
          border: none;
          border-radius: 8px;
          cursor: pointer;
          transition: all 0.2s;
        }

        .btn:disabled {
          opacity: 0.6;
          cursor: not-allowed;
        }

        .btn-primary {
          background: linear-gradient(135deg, #38bdf8 0%, #0ea5e9 100%);
          color: white;
          box-shadow: 0 2px 8px rgba(56, 189, 248, 0.3);
        }

        .btn-primary:hover:not(:disabled) {
          background: linear-gradient(135deg, #0ea5e9 0%, #0284c7 100%);
          box-shadow: 0 4px 16px rgba(56, 189, 248, 0.45);
          transform: translateY(-1px);
        }

        .btn-danger {
          background: rgba(248, 113, 113, 0.12);
          color: #f87171;
          border: 1px solid rgba(248, 113, 113, 0.3);
        }

        .btn-danger:hover:not(:disabled) {
          background: rgba(248, 113, 113, 0.2);
          transform: translateY(-1px);
        }

        .btn-icon {
          padding: 10px;
          background: rgba(22, 33, 55, 0.75);
          border: 2px solid rgba(56, 189, 248, 0.22);
          border-radius: 10px;
          cursor: pointer;
          color: #64748b;
          transition: all 0.2s ease;
        }

        .btn-icon:hover {
          background: rgba(56, 189, 248, 0.15);
          border-color: rgba(56, 189, 248, 0.4);
          color: #38bdf8;
        }

        /* Messages */
        .message {
          display: flex;
          align-items: center;
          gap: 10px;
          padding: 12px 16px;
          border-radius: 12px;
          font-size: 0.875rem;
          font-weight: 500;
          margin-top: 12px;
        }

        .message.success {
          background: rgba(52, 211, 153, 0.08);
          color: #34d399;
          border: 1px solid rgba(52, 211, 153, 0.2);
        }

        .message.error {
          background: rgba(248, 113, 113, 0.08);
          color: #f87171;
          border: 1px solid rgba(248, 113, 113, 0.2);
        }

        .message.info {
          background: rgba(56, 189, 248, 0.08);
          color: #7dd3fc;
          border: 1px solid rgba(56, 189, 248, 0.2);
        }

        .provider-message {
          border-radius: 12px;
        }

        /* Query Section */
        .files-section {
          background: rgba(22, 33, 55, 0.8);
          backdrop-filter: blur(12px);
          border: 1px solid rgba(56, 189, 248, 0.2);
          border-radius: 16px;
          padding: 24px;
          box-shadow: 0 4px 24px rgba(0, 0, 0, 0.35), inset 0 1px 0 rgba(255, 255, 255, 0.05), 0 0 0 1px rgba(56, 189, 248, 0.06);
          transition: all 0.3s ease;
        }

        .files-section:hover {
          box-shadow: 0 8px 32px rgba(56, 189, 248, 0.12), inset 0 1px 0 rgba(255, 255, 255, 0.06), 0 0 0 1px rgba(56, 189, 248, 0.1);
          border-color: rgba(56, 189, 248, 0.35);
        }

        .files-section h3 {
          display: flex;
          align-items: center;
          gap: 10px;
          margin: 0 0 20px 0;
          font-size: 1.05rem;
          font-weight: 700;
          color: #f1f5f9;
          padding-bottom: 12px;
          border-bottom: 1px solid rgba(56, 189, 248, 0.18);
        }

        .files-section h3 svg {
          color: #38bdf8;
        }

        /* Files List */
        .files-list {
          display: flex;
          flex-direction: column;
          gap: 8px;
        }

        .file-item {
          display: flex;
          align-items: center;
          gap: 12px;
          padding: 12px 16px;
          background: rgba(15, 23, 42, 0.5);
          border: 1px solid rgba(56, 189, 248, 0.08);
          border-radius: 10px;
          font-size: 0.9rem;
          transition: all 0.2s ease;
        }

        .file-item:hover {
          background: rgba(56, 189, 248, 0.06);
          border-color: rgba(56, 189, 248, 0.2);
        }

        .file-item svg {
          color: #38bdf8;
        }

        .file-name {
          flex: 1;
          color: #e2e8f0;
          font-weight: 500;
        }

        .file-size {
          font-size: 0.8rem;
          color: #94a3b8;
          font-weight: 500;
        }

        /* Stable grid layout for upload row: icon | name | size | status | actions */
        .file-item.file-item-grid {
          display: grid;
          grid-template-columns: 18px minmax(0, 1fr) 70px 96px 116px;
          align-items: center;
          column-gap: 14px;
          padding: 10px 14px;
        }

        .file-item.file-item-grid .file-icon {
          flex: none;
        }

        .file-item.file-item-grid .file-name {
          flex: none;
          min-width: 0;
          overflow: hidden;
          text-overflow: ellipsis;
          white-space: nowrap;
          font-size: 0.875rem;
        }

        .file-item.file-item-grid .file-size {
          text-align: right;
          font-variant-numeric: tabular-nums;
          white-space: nowrap;
          font-size: 0.78rem;
          color: #94a3b8;
          background: transparent;
          padding: 0;
          border: none;
        }

        .file-item.file-item-grid .file-status {
          font-size: 0.72rem;
          font-weight: 500;
          letter-spacing: 0.01em;
          padding: 3px 10px;
          border-radius: 6px;
          white-space: nowrap;
          text-align: center;
          justify-self: center;
          line-height: 1.3;
          display: inline-flex;
          align-items: center;
          gap: 5px;
        }

        .file-item.file-item-grid .file-status::before {
          content: '';
          width: 6px;
          height: 6px;
          border-radius: 50%;
          background: currentColor;
          flex: none;
        }

        .file-item.file-item-grid .file-status.success {
          color: #34d399;
          background: rgba(52, 211, 153, 0.1);
        }

        .file-item.file-item-grid .file-status.idle {
          color: #94a3b8;
          background: rgba(148, 163, 184, 0.08);
        }

        .file-item.file-item-grid .file-status.pending {
          color: #fbbf24;
          background: rgba(251, 191, 36, 0.1);
        }

        .file-item.file-item-grid .action-buttons {
          display: grid;
          grid-template-columns: repeat(3, 32px);
          gap: 4px;
          justify-content: end;
          align-items: center;
          padding: 3px;
          background: rgba(15, 23, 42, 0.4);
          border: 1px solid rgba(56, 189, 248, 0.06);
          border-radius: 8px;
        }

        .file-item.file-item-grid .action-buttons .btn-action-spacer {
          width: 32px;
          height: 32px;
        }

        .file-item.file-item-grid .action-buttons .btn-action {
          width: 32px;
          height: 32px;
          padding: 0;
          display: inline-flex;
          align-items: center;
          justify-content: center;
          border-radius: 6px;
          border: 1px solid transparent;
          background: transparent;
          color: #94a3b8;
          cursor: pointer;
          transition: all 0.12s ease;
        }

        .file-item.file-item-grid .action-buttons .btn-action svg {
          color: inherit;
        }

        .file-item.file-item-grid .action-buttons .btn-action:hover:not(:disabled) {
          background: rgba(56, 189, 248, 0.14);
          color: #e2e8f0;
        }

        .file-item.file-item-grid .action-buttons .btn-action.primary {
          color: #38bdf8;
          background: rgba(56, 189, 248, 0.1);
        }

        .file-item.file-item-grid .action-buttons .btn-action.primary:hover:not(:disabled) {
          background: rgba(56, 189, 248, 0.2);
          color: #7dd3fc;
        }

        .file-item.file-item-grid .action-buttons .btn-action.warning {
          color: #f87171;
        }

        .file-item.file-item-grid .action-buttons .btn-action.warning:hover:not(:disabled) {
          background: rgba(248, 113, 113, 0.14);
          color: #fca5a5;
        }

        .file-item.file-item-grid .action-buttons .btn-action:disabled {
          opacity: 0.35;
          cursor: not-allowed;
        }

        @media (max-width: 720px) {
          .file-item.file-item-grid {
            grid-template-columns: 18px minmax(0, 1fr) auto;
            grid-template-areas:
              "icon name size"
              "status status status"
              "actions actions actions";
            row-gap: 8px;
          }
          .file-item.file-item-grid .file-icon { grid-area: icon; }
          .file-item.file-item-grid .file-name { grid-area: name; }
          .file-item.file-item-grid .file-size { grid-area: size; }
          .file-item.file-item-grid .file-status { grid-area: status; justify-self: start; }
          .file-item.file-item-grid .action-buttons { grid-area: actions; justify-content: start; }
        }

        .pagination-controls {
          display: flex;
          align-items: center;
          justify-content: center;
          gap: 12px;
          margin-top: 12px;
          padding: 8px 0;
        }

        .pagination-controls button {
          padding: 6px 14px;
          border-radius: 8px;
          border: 1px solid rgba(56, 189, 248, 0.2);
          background: rgba(22, 33, 55, 0.6);
          color: #e2e8f0;
          font-size: 0.85rem;
          cursor: pointer;
          transition: all 0.2s ease;
        }

        .pagination-controls button:hover:not(:disabled) {
          background: rgba(56, 189, 248, 0.15);
          border-color: rgba(56, 189, 248, 0.4);
        }

        .pagination-controls button:disabled {
          opacity: 0.4;
          cursor: not-allowed;
        }

        .pagination-controls span {
          font-size: 0.85rem;
          color: #94a3b8;
        }

        /* Animations */
        .spin {
          animation: spin 1s linear infinite;
        }

        @keyframes spin {
          from {
            transform: rotate(0deg);
          }
          to {
            transform: rotate(360deg);
          }
        }

        /* Quiz Section */
        .quiz-section {
          background: rgba(22, 33, 55, 0.8);
          backdrop-filter: blur(12px);
          border: 1px solid rgba(56, 189, 248, 0.2);
          border-radius: 16px;
          padding: 24px;
          box-shadow: 0 4px 24px rgba(0, 0, 0, 0.35), inset 0 1px 0 rgba(255, 255, 255, 0.05), 0 0 0 1px rgba(56, 189, 248, 0.06);
        }

        .quiz-section h3 {
          display: flex;
          align-items: center;
          gap: 10px;
          margin: 0 0 20px 0;
          font-size: 1.05rem;
          font-weight: 700;
          color: #f1f5f9;
          padding-bottom: 12px;
          border-bottom: 1px solid rgba(56, 189, 248, 0.18);
        }

        .quiz-section h3 svg {
          color: #38bdf8;
        }

        .quiz-form {
          display: flex;
          flex-direction: column;
          gap: 16px;
        }

        .form-group {
          display: flex;
          flex-direction: column;
          gap: 6px;
        }

        /* Document selector for topic suggestions */
        .document-selector {
          margin-bottom: 8px;
        }

        .document-selector label {
          display: flex;
          align-items: center;
          gap: 6px;
          font-size: 0.875rem;
          font-weight: 500;
          color: #94a3b8;
        }

        .document-select {
          padding: 8px 12px;
          border: 1px solid rgba(56, 189, 248, 0.22);
          border-radius: 8px;
          font-size: 0.875rem;
          background: rgba(22, 33, 55, 0.7);
          color: #e2e8f0;
          cursor: pointer;
          transition: all 0.2s;
        }

        .document-select:hover {
          border-color: rgba(56, 189, 248, 0.4);
        }

        .document-select:focus {
          outline: none;
          border-color: #38bdf8;
          box-shadow: 0 0 0 3px rgba(56, 189, 248, 0.12);
        }

        .topic-input-group {
          position: relative;
        }

        .topic-input-wrapper {
          display: flex;
          gap: 8px;
        }

        .topic-input-wrapper input {
          flex: 1;
        }

        .btn-suggest-topics {
          display: flex;
          align-items: center;
          gap: 6px;
          padding: 8px 12px;
          background: rgba(22, 33, 55, 0.75);
          border: 1px solid rgba(56, 189, 248, 0.22);
          border-radius: 8px;
          font-size: 0.8125rem;
          color: #94a3b8;
          cursor: pointer;
          transition: all 0.2s;
          white-space: nowrap;
        }

        .btn-suggest-topics:hover:not(:disabled) {
          background: rgba(56, 189, 248, 0.08);
          border-color: #38bdf8;
          color: #38bdf8;
        }

        .btn-suggest-topics:disabled {
          opacity: 0.5;
          cursor: not-allowed;
        }

        .topic-suggestions {
          position: absolute;
          top: 100%;
          left: 0;
          right: 0;
          margin-top: 4px;
          background: rgba(22, 33, 55, 0.97);
          backdrop-filter: blur(16px);
          border: 1px solid rgba(56, 189, 248, 0.25);
          border-radius: 8px;
          box-shadow: 0 4px 24px rgba(0, 0, 0, 0.4), 0 0 0 1px rgba(56, 189, 248, 0.08);
          z-index: 100;
          max-height: 300px;
          overflow-y: auto;
        }

        .suggestions-header {
          display: flex;
          justify-content: space-between;
          align-items: center;
          padding: 10px 12px;
          border-bottom: 1px solid rgba(56, 189, 248, 0.18);
          font-size: 0.8125rem;
          font-weight: 500;
          color: #94a3b8;
        }

        .btn-close-suggestions {
          display: flex;
          align-items: center;
          justify-content: center;
          padding: 4px;
          background: none;
          border: none;
          color: #64748b;
          cursor: pointer;
          border-radius: 4px;
        }

        .btn-close-suggestions:hover {
          background: rgba(56, 189, 248, 0.08);
          color: #94a3b8;
        }

        .suggestions-list {
          list-style: none;
          padding: 0;
          margin: 0;
        }

        .suggestion-item {
          display: flex;
          flex-direction: column;
          gap: 2px;
          padding: 10px 12px;
          cursor: pointer;
          transition: background 0.15s;
          border-bottom: 1px solid rgba(56, 189, 248, 0.06);
        }

        .suggestion-item:last-child {
          border-bottom: none;
        }

        .suggestion-item:hover {
          background: rgba(56, 189, 248, 0.08);
        }

        .topic-name {
          font-size: 0.9rem;
          font-weight: 600;
          color: #e2e8f0;
        }

        .topic-description {
          font-size: 0.8rem;
          color: #94a3b8;
          line-height: 1.4;
        }

        .form-group label {
          font-size: 0.875rem;
          font-weight: 600;
          color: #cbd5e1;
        }

        .form-group input,
        .form-group select {
          padding: 12px 14px;
          border: 2px solid rgba(56, 189, 248, 0.22);
          border-radius: 10px;
          font-size: 0.9rem;
          color: #e2e8f0;
          background: rgba(22, 33, 55, 0.7);
          transition: all 0.2s ease;
        }

        .form-group input::placeholder {
          color: #64748b;
        }

        .form-group input:focus,
        .form-group select:focus {
          outline: none;
          border-color: #38bdf8;
          background: rgba(15, 23, 42, 0.8);
          box-shadow: 0 0 0 4px rgba(56, 189, 248, 0.12);
        }

        .form-row {
          display: grid;
          grid-template-columns: repeat(3, 1fr);
          gap: 12px;
        }

        .btn-generate {
          width: 100%;
          justify-content: center;
          padding: 12px;
        }

        /* Quiz Display */
        .quiz-display {
          margin-top: 24px;
          border-top: 1px solid rgba(56, 189, 248, 0.1);
          padding-top: 24px;
        }

        .quiz-header {
          display: flex;
          align-items: center;
          justify-content: space-between;
          margin-bottom: 20px;
        }

        .quiz-header h4 {
          display: flex;
          align-items: center;
          gap: 8px;
          margin: 0;
          font-size: 1.1rem;
          color: #e2e8f0;
        }

        .quiz-score {
          padding: 8px 16px;
          background: linear-gradient(135deg, #38bdf8 0%, #0ea5e9 100%);
          color: white;
          border-radius: 20px;
          font-weight: 600;
          font-size: 0.875rem;
        }

        .quiz-questions {
          display: flex;
          flex-direction: column;
          gap: 20px;
        }

        .quiz-question {
          background: rgba(22, 33, 55, 0.7);
          backdrop-filter: blur(12px);
          border: 1px solid rgba(56, 189, 248, 0.18);
          border-radius: 16px;
          padding: 24px;
          transition: all 0.2s ease;
          box-shadow: 0 2px 12px rgba(0, 0, 0, 0.2), inset 0 1px 0 rgba(255, 255, 255, 0.03);
          box-shadow: 0 4px 16px rgba(0, 0, 0, 0.1);
        }

        .quiz-question:hover {
          border-color: rgba(56, 189, 248, 0.2);
          box-shadow: 0 4px 20px rgba(56, 189, 248, 0.06);
        }

        .quiz-question.editing {
          border-color: rgba(56, 189, 248, 0.4);
          background: rgba(56, 189, 248, 0.04);
          box-shadow: 0 4px 20px rgba(56, 189, 248, 0.1);
        }

        .quiz-question.correct {
          border-color: #10b981;
          background: rgba(34, 197, 94, 0.08);
        }

        .quiz-question.incorrect {
          border-color: #ef4444;
          background: rgba(220, 38, 38, 0.08);
        }

        .question-header {
          display: flex;
          align-items: center;
          justify-content: space-between;
          margin-bottom: 12px;
        }

        .question-number {
          font-weight: 700;
          color: white;
          font-size: 0.8rem;
          background: linear-gradient(135deg, #38bdf8 0%, #0ea5e9 100%);
          padding: 6px 14px;
          border-radius: 20px;
          box-shadow: 0 2px 8px rgba(56, 189, 248, 0.3);
        }

        .btn-edit-question {
          display: flex;
          align-items: center;
          justify-content: center;
          gap: 6px;
          padding: 6px 12px;
          border: 1px solid rgba(56, 189, 248, 0.15);
          background: rgba(15, 23, 42, 0.6);
          border-radius: 8px;
          cursor: pointer;
          color: #94a3b8;
          transition: all 0.2s;
          font-size: 13px;
          font-weight: 500;
          white-space: nowrap;
        }

        .btn-edit-question:hover {
          background: rgba(56, 189, 248, 0.08);
          border-color: #38bdf8;
          color: #38bdf8;
        }

        .question-edit-actions {
          display: flex;
          justify-content: flex-end;
          gap: 8px;
          margin-top: 16px;
          padding-top: 16px;
          border-top: 1px solid rgba(56, 189, 248, 0.1);
        }

        .btn.btn-sm {
          padding: 6px 12px;
          font-size: 0.8125rem;
        }

        .btn.btn-success {
          background: linear-gradient(135deg, #10b981 0%, #059669 100%);
          color: white;
          border: none;
        }

        .btn.btn-success:hover {
          background: linear-gradient(135deg, #059669 0%, #047857 100%);
        }

        .answer-status {
          display: flex;
          align-items: center;
          gap: 4px;
          font-size: 0.8125rem;
          font-weight: 500;
        }

        .answer-status.correct {
          color: #34d399;
        }

        .answer-status.incorrect {
          color: #f87171;
        }

        .question-text {
          font-size: 1rem;
          font-weight: 600;
          margin-bottom: 20px;
          line-height: 1.6;
          color: #e2e8f0;
        }

        .question-options {
          display: flex;
          flex-direction: column;
          gap: 10px;
        }

        .option-label {
          display: flex;
          align-items: center;
          gap: 14px;
          padding: 14px 18px;
          background: rgba(15, 23, 42, 0.5);
          border: 1px solid rgba(56, 189, 248, 0.1);
          border-radius: 12px;
          cursor: pointer;
          transition: all 0.2s ease;
        }

        .option-label:hover:not(.correct-answer):not(.wrong-answer) {
          border-color: rgba(56, 189, 248, 0.3);
          background: rgba(56, 189, 248, 0.06);
        }

        .option-label.selected {
          border-color: #38bdf8;
          background: rgba(56, 189, 248, 0.1);
        }

        .option-label.correct-answer {
          border-color: #10b981;
          background: rgba(34, 197, 94, 0.1);
        }

        .option-label.wrong-answer {
          border-color: #ef4444;
          background: rgba(220, 38, 38, 0.1);
        }

        .option-label input {
          cursor: pointer;
        }

        .option-key {
          font-weight: 700;
          color: #94a3b8;
          min-width: 28px;
          height: 28px;
          display: flex;
          align-items: center;
          justify-content: center;
          background: rgba(100, 116, 139, 0.15);
          border: 1px solid rgba(100, 116, 139, 0.2);
          border-radius: 8px;
          font-size: 0.85rem;
        }

        .correct-answer .option-key {
          background: rgba(52, 211, 153, 0.15);
          border-color: #34d399;
          color: #34d399;
        }

        .option-value {
          font-size: 0.9rem;
          color: #e2e8f0;
          font-weight: 500;
        }

        .question-explanation {
          margin-top: 20px;
          padding: 16px;
          background: rgba(251, 191, 36, 0.06);
          border: 1px solid rgba(251, 191, 36, 0.2);
          border-radius: 12px;
          font-size: 0.875rem;
          color: #fbbf24;
          font-weight: 500;
          line-height: 1.5;
        }

        .question-explanation::before {
          content: '💡 ';
        }

        .quiz-actions {
          margin-top: 24px;
          display: flex;
          justify-content: center;
          gap: 12px;
        }

        .quiz-actions .btn {
          min-width: 200px;
          justify-content: center;
        }

        /* Quiz Edit Mode */
        .quiz-header-actions {
          display: flex;
          gap: 12px;
        }

        .btn-secondary {
          background: rgba(22, 33, 55, 0.75);
          color: #94a3b8;
          border: 1px solid rgba(56, 189, 248, 0.22);
        }

        .btn-secondary:hover:not(:disabled) {
          background: rgba(56, 189, 248, 0.12);
          color: #e2e8f0;
          border-color: rgba(56, 189, 248, 0.4);
        }

        .edit-question-text {
          width: 100%;
          padding: 14px;
          border: 2px solid rgba(56, 189, 248, 0.22);
          border-radius: 10px;
          font-size: 1rem;
          font-weight: 500;
          margin-bottom: 16px;
          font-family: inherit;
          resize: vertical;
          color: #e2e8f0;
          background: rgba(22, 33, 55, 0.7);
        }

        .edit-question-text:focus {
          outline: none;
          border-color: #38bdf8;
          box-shadow: 0 0 0 3px rgba(56, 189, 248, 0.12);
        }

        .question-options.edit-mode {
          display: flex;
          flex-direction: column;
          gap: 12px;
        }

        .edit-option {
          display: flex;
          align-items: center;
          gap: 12px;
          padding: 14px;
          background: rgba(15, 23, 42, 0.5);
          border: 1px solid rgba(56, 189, 248, 0.1);
          border-radius: 12px;
        }

        .edit-option-input {
          flex: 1;
          padding: 10px 14px;
          border: 2px solid rgba(56, 189, 248, 0.15);
          border-radius: 8px;
          font-size: 0.9rem;
          color: #e2e8f0;
          background: rgba(15, 23, 42, 0.6);
        }

        .edit-option-input:focus {
          outline: none;
          border-color: #38bdf8;
        }

        .correct-label {
          display: flex;
          align-items: center;
          gap: 6px;
          font-size: 0.8125rem;
          color: #34d399;
          font-weight: 500;
          white-space: nowrap;
          cursor: pointer;
        }

        .edit-explanation {
          margin-top: 16px;
          display: flex;
          flex-direction: column;
          gap: 8px;
        }

        .edit-explanation label {
          font-size: 0.875rem;
          font-weight: 500;
          color: #94a3b8;
        }

        .edit-explanation textarea {
          width: 100%;
          padding: 10px 12px;
          border: 1px solid rgba(56, 189, 248, 0.22);
          border-radius: 8px;
          font-size: 0.8125rem;
          font-family: inherit;
          resize: vertical;
          color: #e2e8f0;
          background: rgba(22, 33, 55, 0.7);
        }

        .edit-explanation textarea:focus {
          outline: none;
          border-color: #38bdf8;
          box-shadow: 0 0 0 3px rgba(56, 189, 248, 0.12);
        }

        .correct-icon {
          margin-left: auto;
        }

        /* ===== NEW IMPROVED TOPIC SELECTOR STYLES ===== */
        
        /* Selected Topics Preview at Top */
        .selected-topics-preview {
          background: rgba(52, 211, 153, 0.08);
          border: 1px solid rgba(52, 211, 153, 0.25);
          border-radius: 16px;
          padding: 16px;
          margin-bottom: 20px;
          box-shadow: 0 2px 10px rgba(0, 0, 0, 0.15), inset 0 1px 0 rgba(52, 211, 153, 0.05);
        }

        .selected-topics-header {
          display: flex;
          align-items: center;
          justify-content: space-between;
          margin-bottom: 12px;
        }

        .selected-count {
          display: flex;
          align-items: center;
          gap: 8px;
          font-size: 0.9rem;
          font-weight: 600;
          color: #34d399;
        }

        .btn-clear-all {
          display: flex;
          align-items: center;
          gap: 4px;
          padding: 6px 12px;
          background: rgba(248, 113, 113, 0.08);
          border: 1px solid rgba(248, 113, 113, 0.2);
          border-radius: 8px;
          font-size: 0.8rem;
          font-weight: 500;
          color: #f87171;
          cursor: pointer;
          transition: all 0.2s ease;
        }

        .btn-clear-all:hover {
          background: rgba(248, 113, 113, 0.15);
          border-color: rgba(248, 113, 113, 0.3);
        }

        .selected-topics-chips {
          display: flex;
          flex-wrap: wrap;
          gap: 8px;
        }

        .topic-chip {
          display: inline-flex;
          align-items: center;
          gap: 6px;
          padding: 6px 12px;
          background: rgba(52, 211, 153, 0.08);
          border: 1px solid rgba(52, 211, 153, 0.2);
          border-radius: 20px;
          font-size: 0.85rem;
          font-weight: 500;
          color: #34d399;
        }

        .chip-remove {
          display: flex;
          align-items: center;
          justify-content: center;
          width: 18px;
          height: 18px;
          padding: 0;
          background: rgba(248, 113, 113, 0.1);
          border: none;
          border-radius: 50%;
          cursor: pointer;
          color: #f87171;
          transition: all 0.15s ease;
        }

        .chip-remove:hover {
          background: rgba(248, 113, 113, 0.2);
          color: #ef4444;
        }

        /* Document Topic Selector */
        .document-topic-selector {
          margin-bottom: 20px;
        }

        .selector-label {
          display: flex;
          align-items: center;
          gap: 8px;
          font-size: 0.9rem;
          font-weight: 600;
          color: #cbd5e1;
          margin-bottom: 12px;
        }

        .document-cards {
          display: flex;
          flex-direction: column;
          gap: 12px;
        }

        .document-card {
          background: rgba(22, 33, 55, 0.75);
          backdrop-filter: blur(12px);
          border: 1px solid rgba(56, 189, 248, 0.18);
          border-radius: 16px;
          overflow: hidden;
          transition: all 0.2s ease;
          box-shadow: 0 2px 12px rgba(0, 0, 0, 0.2), inset 0 1px 0 rgba(255, 255, 255, 0.03);
        }

        .document-card:hover {
          border-color: rgba(56, 189, 248, 0.35);
          box-shadow: 0 4px 20px rgba(56, 189, 248, 0.1), inset 0 1px 0 rgba(255, 255, 255, 0.05);
        }

        .document-card.expanded {
          border-color: rgba(56, 189, 248, 0.4);
          box-shadow: 0 6px 24px rgba(56, 189, 248, 0.15), inset 0 1px 0 rgba(255, 255, 255, 0.06);
        }

        .document-card-header {
          display: flex;
          align-items: center;
          justify-content: space-between;
          padding: 16px;
          cursor: pointer;
          transition: background 0.15s ease;
        }

        .document-card-header:hover {
          background: rgba(56, 189, 248, 0.04);
        }

        .document-card.expanded .document-card-header {
          background: rgba(56, 189, 248, 0.08);
          border-bottom: 1px solid rgba(56, 189, 248, 0.18);
        }

        .doc-info {
          display: flex;
          align-items: center;
          gap: 12px;
        }

        .doc-icon {
          color: #38bdf8;
        }

        .doc-details {
          display: flex;
          flex-direction: column;
          gap: 2px;
        }

        .doc-details .doc-name {
          font-size: 0.95rem;
          font-weight: 600;
          color: #e2e8f0;
        }

        .doc-details .doc-meta {
          font-size: 0.8rem;
          color: #64748b;
        }

        .doc-actions {
          display: flex;
          align-items: center;
          gap: 12px;
        }

        .selected-badge {
          padding: 4px 10px;
          background: linear-gradient(135deg, #10b981 0%, #059669 100%);
          color: white;
          border-radius: 12px;
          font-size: 0.75rem;
          font-weight: 600;
        }

        .expand-icon {
          display: flex;
          align-items: center;
          justify-content: center;
          width: 32px;
          height: 32px;
          background: rgba(100, 116, 139, 0.15);
          border-radius: 8px;
          color: #64748b;
          transition: all 0.2s ease;
        }

        .expand-icon.expanded {
          background: linear-gradient(135deg, #38bdf8 0%, #0ea5e9 100%);
          color: white;
          transform: rotate(180deg);
        }

        .document-card-content {
          padding: 16px;
          background: rgba(15, 23, 42, 0.5);
          border-top: 1px solid rgba(56, 189, 248, 0.12);
        }

        .topics-toolbar {
          display: flex;
          justify-content: flex-end;
          margin-bottom: 12px;
        }

        .btn-select-all {
          display: flex;
          align-items: center;
          gap: 6px;
          padding: 6px 12px;
          background: rgba(22, 33, 55, 0.75);
          border: 1px solid rgba(56, 189, 248, 0.22);
          border-radius: 8px;
          font-size: 0.8rem;
          font-weight: 500;
          color: #94a3b8;
          cursor: pointer;
          transition: all 0.15s ease;
        }

        .btn-select-all:hover {
          background: rgba(56, 189, 248, 0.12);
          border-color: rgba(56, 189, 248, 0.4);
          color: #38bdf8;
        }

        .topics-grid {
          display: flex;
          flex-wrap: wrap;
          gap: 10px;
        }

        .topic-tag {
          display: inline-flex;
          align-items: center;
          gap: 6px;
          padding: 10px 16px;
          background: rgba(22, 33, 55, 0.65);
          border: 1px solid rgba(56, 189, 248, 0.18);
          border-radius: 25px;
          font-size: 0.875rem;
          font-weight: 500;
          color: #cbd5e1;
          cursor: pointer;
          transition: all 0.2s ease;
        }

        .topic-tag:hover:not(:disabled) {
          border-color: rgba(56, 189, 248, 0.4);
          background: rgba(56, 189, 248, 0.12);
          transform: translateY(-1px);
        }

        .topic-tag.selected {
          background: linear-gradient(135deg, #38bdf8 0%, #0ea5e9 100%);
          border-color: #0ea5e9;
          color: white;
          box-shadow: 0 2px 8px rgba(56, 189, 248, 0.35);
        }

        .topic-tag .check-icon {
          color: white;
        }

        .topic-tag:disabled {
          opacity: 0.6;
          cursor: not-allowed;
        }

        .loading-topics {
          display: flex;
          align-items: center;
          justify-content: center;
          gap: 10px;
          padding: 24px;
          color: #64748b;
          font-size: 0.9rem;
        }

        /* Topic Selector Section */
        .topic-selector-section {
          margin-bottom: 16px;
        }

        .section-label {
          display: flex;
          align-items: center;
          gap: 8px;
          font-weight: 600;
          color: #e2e8f0;
          margin-bottom: 12px;
          font-size: 0.95rem;
        }

        .btn-select-topics {
          display: flex;
          align-items: center;
          justify-content: space-between;
          width: 100%;
          padding: 16px 20px;
          border: 2px dashed rgba(56, 189, 248, 0.3);
          border-radius: 12px;
          background: rgba(22, 33, 55, 0.55);
          color: #64748b;
          font-size: 0.95rem;
          font-weight: 500;
          cursor: pointer;
          transition: all 0.2s ease;
        }

        .btn-select-topics:hover:not(:disabled) {
          border-color: rgba(56, 189, 248, 0.5);
          background: rgba(56, 189, 248, 0.08);
          color: #38bdf8;
        }

        .btn-select-topics:disabled {
          opacity: 0.6;
          cursor: not-allowed;
        }

        .btn-select-topics span {
          flex: 1;
          text-align: left;
          margin-left: 8px;
        }

        .no-docs-hint {
          display: flex;
          align-items: center;
          gap: 8px;
          margin-top: 8px;
          padding: 12px 16px;
          background: rgba(251, 191, 36, 0.08);
          border: 1px solid rgba(251, 191, 36, 0.25);
          border-radius: 10px;
          color: #fbbf24;
          font-size: 0.85rem;
          box-shadow: 0 2px 8px rgba(0, 0, 0, 0.1);
        }

        .selected-topics-preview {
          background: rgba(52, 211, 153, 0.08);
          border: 1px solid rgba(52, 211, 153, 0.25);
          border-radius: 12px;
          padding: 16px;
          box-shadow: 0 2px 8px rgba(0, 0, 0, 0.1);
        }

        .selected-topics-header {
          display: flex;
          align-items: center;
          justify-content: space-between;
          margin-bottom: 12px;
        }

        .selected-count {
          display: flex;
          align-items: center;
          gap: 8px;
          color: #34d399;
          font-weight: 600;
          font-size: 0.9rem;
        }

        .preview-actions {
          display: flex;
          gap: 8px;
        }

        .btn-edit-topics,
        .btn-clear-all {
          display: flex;
          align-items: center;
          gap: 4px;
          padding: 6px 12px;
          border: none;
          border-radius: 8px;
          font-size: 0.8rem;
          font-weight: 500;
          cursor: pointer;
          transition: all 0.2s ease;
        }

        .btn-edit-topics {
          background: linear-gradient(135deg, #38bdf8 0%, #0ea5e9 100%);
          color: white;
        }

        .btn-edit-topics:hover {
          background: linear-gradient(135deg, #0ea5e9 0%, #0284c7 100%);
        }

        .btn-clear-all {
          background: rgba(248, 113, 113, 0.08);
          color: #f87171;
        }

        .btn-clear-all:hover {
          background: rgba(248, 113, 113, 0.15);
        }

        .selected-topics-chips {
          display: flex;
          flex-wrap: wrap;
          gap: 8px;
        }

        .topic-chip {
          display: inline-flex;
          align-items: center;
          gap: 6px;
          padding: 6px 12px;
          background: rgba(52, 211, 153, 0.08);
          border: 1px solid rgba(52, 211, 153, 0.2);
          border-radius: 20px;
          font-size: 0.82rem;
          color: #34d399;
          font-weight: 500;
        }

        .topic-chip.more {
          background: rgba(52, 211, 153, 0.06);
          color: #34d399;
          font-style: italic;
        }

        /* Modal Styles */
        .modal-overlay {
          position: fixed;
          top: 0;
          left: 0;
          right: 0;
          bottom: 0;
          background: rgba(0, 0, 0, 0.75);
          display: flex;
          align-items: center;
          justify-content: center;
          z-index: 1000;
          padding: 20px;
          animation: fadeIn 0.2s ease;
          backdrop-filter: blur(4px);
        }

        @keyframes fadeIn {
          from { opacity: 0; }
          to { opacity: 1; }
        }

        .topic-modal {
          background: rgba(22, 33, 55, 0.97);
          backdrop-filter: blur(20px);
          border: 1px solid rgba(56, 189, 248, 0.25);
          border-radius: 16px;
          width: 100%;
          max-width: 700px;
          max-height: 85vh;
          display: flex;
          flex-direction: column;
          box-shadow: 0 20px 60px rgba(0, 0, 0, 0.6), 0 0 40px rgba(56, 189, 248, 0.08), inset 0 1px 0 rgba(255, 255, 255, 0.05);
          animation: slideUp 0.3s ease;
        }

        @keyframes slideUp {
          from {
            opacity: 0;
            transform: translateY(20px);
          }
          to {
            opacity: 1;
            transform: translateY(0);
          }
        }

        .modal-header {
          display: flex;
          align-items: center;
          justify-content: space-between;
          padding: 20px 24px;
          border-bottom: 1px solid rgba(56, 189, 248, 0.18);
          background: rgba(15, 23, 42, 0.4);
        }

        .modal-header h3 {
          display: flex;
          align-items: center;
          gap: 10px;
          margin: 0;
          font-size: 1.15rem;
          font-weight: 600;
          color: #e2e8f0;
        }

        .modal-header h3 svg {
          color: #38bdf8;
        }

        .modal-close {
          display: flex;
          align-items: center;
          justify-content: center;
          gap: 6px;
          padding: 0 12px;
          height: 40px;
          min-width: 80px;
          border: 1px solid rgba(248, 113, 113, 0.2);
          border-radius: 12px;
          background: rgba(248, 113, 113, 0.06);
          color: #f87171;
          font-size: 0.9rem;
          font-weight: 600;
          cursor: pointer;
          transition: all 0.2s ease;
          flex-shrink: 0;
        }

        .modal-close svg {
          width: 16px;
          height: 16px;
          stroke-width: 2.5;
          transition: all 0.2s ease;
        }

        .modal-close span {
          transition: all 0.2s ease;
        }

        .modal-close:hover {
          background: rgba(248, 113, 113, 0.12);
          border-color: rgba(248, 113, 113, 0.35);
          color: #ef4444;
          transform: scale(1.02);
        }

        .modal-close:active {
          transform: scale(0.98);
        }

        /* Topic Source Selector */
        .topic-source-selector {
          display: flex;
          gap: 8px;
          padding: 16px 24px;
          background: rgba(15, 23, 42, 0.5);
          border-bottom: 1px solid rgba(56, 189, 248, 0.12);
        }

        .source-tab {
          flex: 1;
          display: flex;
          align-items: center;
          justify-content: center;
          gap: 8px;
          padding: 12px 16px;
          border: 1px solid rgba(56, 189, 248, 0.18);
          border-radius: 10px;
          background: rgba(22, 33, 55, 0.65);
          color: #64748b;
          font-size: 0.9rem;
          font-weight: 600;
          cursor: pointer;
          transition: all 0.2s ease;
        }

        .source-tab:hover {
          border-color: rgba(56, 189, 248, 0.4);
          color: #38bdf8;
          background: rgba(56, 189, 248, 0.1);
        }

        .source-tab.active {
          border-color: #38bdf8;
          background: linear-gradient(135deg, #38bdf8 0%, #0ea5e9 100%);
          color: white;
        }

        .source-tab .source-count {
          display: inline-flex;
          align-items: center;
          justify-content: center;
          min-width: 24px;
          height: 24px;
          padding: 0 8px;
          border-radius: 12px;
          font-size: 0.8rem;
          font-weight: 700;
          background: rgba(0, 0, 0, 0.1);
        }

        .source-tab.active .source-count {
          background: rgba(255, 255, 255, 0.25);
        }

        /* Modal Empty State */
        .modal-empty-state {
          display: flex;
          flex-direction: column;
          align-items: center;
          justify-content: center;
          padding: 48px 24px;
          color: #64748b;
          text-align: center;
        }

        .modal-empty-state svg {
          margin-bottom: 16px;
          opacity: 0.5;
        }

        .modal-empty-state p {
          margin: 0;
          font-size: 0.95rem;
          line-height: 1.6;
          max-width: 300px;
        }

        .modal-body {
          flex: 1;
          overflow-y: auto;
          padding: 20px 24px;
        }

        /* Custom Scrollbar for Modal */
        .modal-body::-webkit-scrollbar,
        .quiz-modal-body::-webkit-scrollbar {
          width: 8px;
        }

        .modal-body::-webkit-scrollbar-track,
        .quiz-modal-body::-webkit-scrollbar-track {
          background: rgba(15, 23, 42, 0.3);
          border-radius: 10px;
        }

        .modal-body::-webkit-scrollbar-thumb,
        .quiz-modal-body::-webkit-scrollbar-thumb {
          background: rgba(56, 189, 248, 0.15);
          border-radius: 10px;
          border: 2px solid transparent;
        }

        .modal-body::-webkit-scrollbar-thumb:hover,
        .quiz-modal-body::-webkit-scrollbar-thumb:hover {
          background: rgba(56, 189, 248, 0.25);
        }

        .modal-selected-summary {
          display: flex;
          align-items: center;
          padding: 12px 16px;
          background: rgba(52, 211, 153, 0.08);
          border: 1px solid rgba(52, 211, 153, 0.25);
          border-radius: 10px;
          margin-bottom: 16px;
          box-shadow: 0 2px 8px rgba(0, 0, 0, 0.1);
        }

        .summary-label {
          display: flex;
          align-items: center;
          gap: 8px;
          color: #34d399;
          font-weight: 600;
          font-size: 0.9rem;
        }

        .modal-documents {
          display: flex;
          flex-direction: column;
          gap: 12px;
        }

        /* Course group styles for Canvas tab */
        .course-group {
          border: 1px solid rgba(56, 189, 248, 0.15);
          border-radius: 14px;
          overflow: hidden;
          background: rgba(15, 23, 42, 0.3);
        }

        .course-group-header {
          display: flex;
          align-items: center;
          gap: 10px;
          padding: 12px 16px;
          background: rgba(15, 23, 42, 0.6);
          cursor: pointer;
          transition: background 0.2s ease;
          user-select: none;
        }

        .course-group-header:hover {
          background: rgba(56, 189, 248, 0.08);
        }

        .course-expand-icon {
          display: flex;
          align-items: center;
          color: rgba(148, 163, 184, 0.8);
          transition: transform 0.2s ease;
        }

        .course-icon {
          color: rgba(56, 189, 248, 0.7);
          flex-shrink: 0;
        }

        .course-group-name {
          font-weight: 600;
          font-size: 0.92rem;
          color: rgba(226, 232, 240, 0.95);
          flex: 1;
          min-width: 0;
          overflow: hidden;
          text-overflow: ellipsis;
          white-space: nowrap;
        }

        .course-group-badge {
          font-size: 0.78rem;
          color: rgba(148, 163, 184, 0.8);
          background: rgba(56, 189, 248, 0.1);
          padding: 2px 10px;
          border-radius: 10px;
          white-space: nowrap;
          flex-shrink: 0;
        }

        .course-group-docs {
          display: flex;
          flex-direction: column;
          gap: 8px;
          padding: 10px 12px;
        }

        .course-group-docs .modal-doc-card {
          border-radius: 10px;
        }

        .modal-doc-card {
          border: 1px solid rgba(56, 189, 248, 0.18);
          border-radius: 12px;
          overflow: hidden;
          transition: all 0.2s ease;
          background: rgba(22, 33, 55, 0.5);
        }

        .modal-doc-card:hover {
          border-color: rgba(56, 189, 248, 0.35);
        }

        .modal-doc-card.expanded {
          border-color: rgba(56, 189, 248, 0.4);
          box-shadow: 0 4px 20px rgba(56, 189, 248, 0.12);
        }

        .modal-doc-header {
          display: flex;
          align-items: center;
          gap: 12px;
          padding: 14px 16px;
          background: rgba(15, 23, 42, 0.5);
          cursor: pointer;
          transition: background 0.2s ease;
        }

        .modal-doc-header:hover {
          background: rgba(56, 189, 248, 0.08);
        }

        .modal-doc-card.expanded .modal-doc-header {
          background: rgba(56, 189, 248, 0.08);
          border-bottom: 1px solid rgba(56, 189, 248, 0.14);
        }

        .modal-doc-checkbox {
          display: flex;
          align-items: center;
        }

        .modal-doc-checkbox input[type="checkbox"] {
          width: 18px;
          height: 18px;
          cursor: pointer;
          accent-color: #38bdf8;
        }

        .modal-doc-info {
          display: flex;
          align-items: center;
          gap: 12px;
          flex: 1;
        }

        .modal-doc-info .doc-icon {
          color: #38bdf8;
        }

        .modal-doc-details {
          display: flex;
          flex-direction: column;
          gap: 2px;
        }

        .modal-doc-name {
          font-weight: 600;
          color: #e2e8f0;
          font-size: 0.9rem;
        }

        .modal-doc-meta {
          font-size: 0.8rem;
          color: #64748b;
        }

        .modal-doc-status {
          display: flex;
          align-items: center;
          gap: 8px;
        }

        .modal-selected-badge {
          padding: 4px 10px;
          background: rgba(56, 189, 248, 0.12);
          border-radius: 20px;
          font-size: 0.75rem;
          font-weight: 600;
          color: #38bdf8;
        }

        .modal-expand-icon {
          display: flex;
          align-items: center;
          color: #64748b;
          transition: transform 0.2s ease;
        }

        .modal-expand-icon.expanded {
          transform: rotate(180deg);
        }

        .modal-doc-topics {
          padding: 16px;
          background: rgba(15, 23, 42, 0.5);
        }

        .modal-topics-toolbar {
          margin-bottom: 12px;
        }

        .btn-modal-select-all {
          display: inline-flex;
          align-items: center;
          gap: 6px;
          padding: 6px 12px;
          border: 1px solid rgba(56, 189, 248, 0.22);
          border-radius: 8px;
          background: rgba(22, 33, 55, 0.65);
          color: #94a3b8;
          font-size: 0.8rem;
          font-weight: 500;
          cursor: pointer;
          transition: all 0.2s ease;
        }

        .btn-modal-select-all:hover {
          border-color: rgba(56, 189, 248, 0.4);
          color: #38bdf8;
          background: rgba(56, 189, 248, 0.1);
        }

        .modal-topics-grid {
          display: flex;
          flex-wrap: wrap;
          gap: 8px;
        }

        .modal-topic-tag {
          display: inline-flex;
          align-items: center;
          gap: 6px;
          padding: 8px 14px;
          border: 1px solid rgba(56, 189, 248, 0.18);
          border-radius: 20px;
          background: rgba(22, 33, 55, 0.65);
          font-size: 0.85rem;
          color: #cbd5e1;
          cursor: pointer;
          transition: all 0.2s ease;
        }

        .modal-topic-tag:hover {
          border-color: rgba(56, 189, 248, 0.4);
          background: rgba(56, 189, 248, 0.12);
        }

        .modal-topic-tag.selected {
          background: linear-gradient(135deg, #38bdf8 0%, #0ea5e9 100%);
          border-color: #0ea5e9;
          color: white;
          box-shadow: 0 2px 8px rgba(56, 189, 248, 0.35);
        }

        .modal-topic-tag .check-icon {
          color: white;
        }

        .modal-loading-topics {
          display: flex;
          align-items: center;
          justify-content: center;
          gap: 10px;
          padding: 24px;
          color: #64748b;
          font-size: 0.9rem;
        }

        .modal-footer {
          display: flex;
          align-items: center;
          justify-content: flex-end;
          gap: 12px;
          padding: 16px 24px;
          border-top: 1px solid rgba(56, 189, 248, 0.18);
          background: rgba(15, 23, 42, 0.5);
        }

        .modal-footer .btn {
          display: flex;
          align-items: center;
          gap: 8px;
          padding: 10px 20px;
          border-radius: 10px;
          font-weight: 600;
          font-size: 0.9rem;
          cursor: pointer;
          transition: all 0.2s ease;
        }

        .modal-footer .btn-secondary {
          background: rgba(15, 23, 42, 0.6);
          border: 1px solid rgba(56, 189, 248, 0.15);
          color: #94a3b8;
        }

        .modal-footer .btn-secondary:hover {
          background: rgba(56, 189, 248, 0.08);
          color: #e2e8f0;
        }

        .modal-footer .btn-primary {
          background: linear-gradient(135deg, #38bdf8 0%, #0ea5e9 100%);
          border: none;
          color: white;
        }

        .modal-footer .btn-primary:hover:not(:disabled) {
          background: linear-gradient(135deg, #0ea5e9 0%, #0284c7 100%);
          transform: translateY(-1px);
          box-shadow: 0 4px 12px rgba(56, 189, 248, 0.4);
        }

        .modal-footer .btn-primary:disabled {
          background: rgba(100, 116, 139, 0.3);
          cursor: not-allowed;
        }

        /* Quiz Preview Section */
        .quiz-preview-section {
          margin-top: 20px;
        }

        .quiz-preview-card {
          display: flex;
          align-items: center;
          justify-content: space-between;
          padding: 16px 20px;
          background: rgba(52, 211, 153, 0.06);
          border: 1px solid rgba(52, 211, 153, 0.2);
          border-radius: 12px;
          gap: 16px;
        }

        .quiz-preview-info {
          display: flex;
          align-items: center;
          gap: 12px;
          flex: 1;
        }

        .quiz-preview-info .quiz-icon {
          color: #34d399;
        }

        .quiz-preview-details {
          display: flex;
          flex-direction: column;
          gap: 2px;
        }

        .quiz-preview-title {
          font-weight: 600;
          color: #34d399;
          font-size: 0.95rem;
        }

        .quiz-preview-meta {
          font-size: 0.82rem;
          color: #94a3b8;
          max-width: 300px;
          white-space: nowrap;
          overflow: hidden;
          text-overflow: ellipsis;
        }

        .quiz-preview-actions {
          display: flex;
          gap: 8px;
        }

        .quiz-preview-actions .btn {
          display: flex;
          align-items: center;
          gap: 6px;
          padding: 8px 16px;
          border-radius: 8px;
          font-size: 0.85rem;
          font-weight: 600;
          cursor: pointer;
          transition: all 0.2s ease;
        }

        .quiz-preview-actions .btn-primary {
          background: linear-gradient(135deg, #38bdf8 0%, #0ea5e9 100%);
          border: none;
          color: white;
        }

        .quiz-preview-actions .btn-primary:hover {
          background: linear-gradient(135deg, #0ea5e9 0%, #0284c7 100%);
          transform: translateY(-1px);
          box-shadow: 0 4px 12px rgba(56, 189, 248, 0.35);
        }

        .quiz-preview-actions .btn-new-quiz {
          background: rgba(52, 211, 153, 0.06);
          border: 1px solid rgba(52, 211, 153, 0.2);
          color: #34d399;
        }

        .quiz-preview-actions .btn-new-quiz:hover {
          background: rgba(52, 211, 153, 0.12);
          border-color: rgba(52, 211, 153, 0.3);
        }

        /* ====== Quiz Modal — Redesigned ====== */
        .quiz-modal {
          background: rgba(13, 20, 40, 0.98);
          backdrop-filter: blur(24px);
          border: 1px solid rgba(56, 189, 248, 0.18);
          border-radius: 18px;
          width: 100%;
          max-width: 860px;
          max-height: 92vh;
          display: flex;
          flex-direction: column;
          box-shadow:
            0 24px 80px rgba(0,0,0,0.55),
            0 0 60px rgba(56, 189, 248, 0.06),
            inset 0 1px 0 rgba(255,255,255,0.04);
          animation: slideUp 0.3s ease;
        }

        /* ── Header ── */
        .quiz-modal-header {
          display: flex;
          align-items: flex-start;
          justify-content: space-between;
          gap: 16px;
          padding: 20px 28px;
          border-bottom: 1px solid rgba(56, 189, 248, 0.12);
          background: linear-gradient(180deg, rgba(15,23,42,0.65) 0%, rgba(15,23,42,0.35) 100%);
          border-radius: 18px 18px 0 0;
        }
        .qm-header-left {
          display: flex;
          align-items: flex-start;
          gap: 14px;
          flex: 1;
          min-width: 0;
        }
        .qm-icon-wrap {
          display: flex;
          align-items: center;
          justify-content: center;
          width: 40px; height: 40px;
          border-radius: 10px;
          background: linear-gradient(135deg, rgba(56,189,248,0.15) 0%, rgba(129,140,248,0.15) 100%);
          color: #38bdf8;
          flex-shrink: 0;
        }
        .qm-header-text {
          min-width: 0;
          flex: 1;
        }
        .qm-header-text h3 {
          margin: 0 0 6px;
          font-size: 1.1rem;
          font-weight: 700;
          color: #f1f5f9;
          white-space: nowrap;
          overflow: hidden;
          text-overflow: ellipsis;
        }
        .qm-header-tags {
          display: flex;
          flex-wrap: wrap;
          gap: 6px;
        }
        .qm-chip {
          display: inline-flex;
          align-items: center;
          gap: 4px;
          padding: 3px 10px;
          border-radius: 20px;
          font-size: 0.72rem;
          font-weight: 600;
          letter-spacing: 0.01em;
        }
        .qm-chip-count {
          background: rgba(56, 189, 248, 0.12);
          color: #38bdf8;
        }
        .qm-chip-difficulty {
          background: rgba(251, 191, 36, 0.1);
          color: #fbbf24;
        }
        .qm-chip-lang {
          background: rgba(148, 163, 184, 0.1);
          color: #94a3b8;
        }
        .qm-chip-source {
          background: rgba(129, 140, 248, 0.12);
          color: #a5b4fc;
        }
        .qm-close-btn {
          display: flex;
          align-items: center;
          justify-content: center;
          width: 34px; height: 34px;
          border-radius: 8px;
          border: 1px solid rgba(148, 163, 184, 0.15);
          background: rgba(15, 23, 42, 0.5);
          color: #94a3b8;
          cursor: pointer;
          transition: all 0.15s;
          flex-shrink: 0;
        }
        .qm-close-btn:hover {
          background: rgba(239, 68, 68, 0.12);
          border-color: rgba(239, 68, 68, 0.3);
          color: #f87171;
        }

        /* ── Body ── */
        .quiz-modal-body {
          flex: 1;
          overflow-y: auto;
          padding: 24px 28px;
        }
        .qm-alert {
          display: flex;
          align-items: center;
          gap: 8px;
          padding: 10px 14px;
          margin-bottom: 16px;
          border-radius: 10px;
          background: rgba(56, 189, 248, 0.06);
          border: 1px solid rgba(56, 189, 248, 0.15);
          color: #7dd3fc;
          font-size: 0.84rem;
        }
        .quiz-questions {
          display: flex;
          flex-direction: column;
          gap: 14px;
        }

        /* ── Question card ── */
        .qm-question {
          background: rgba(22, 33, 55, 0.55);
          border: 1px solid rgba(148, 163, 184, 0.1);
          border-radius: 14px;
          padding: 18px 20px;
          transition: all 0.2s ease;
        }
        .qm-question:hover {
          border-color: rgba(56, 189, 248, 0.22);
          box-shadow: 0 2px 18px rgba(0, 0, 0, 0.15);
        }
        .qm-question-editing {
          border-color: rgba(56, 189, 248, 0.4) !important;
          box-shadow: 0 0 0 3px rgba(56, 189, 248, 0.08), 0 4px 20px rgba(0, 0, 0, 0.2) !important;
          background: rgba(22, 33, 62, 0.7);
        }

        .qm-q-header {
          display: flex;
          align-items: center;
          justify-content: space-between;
          margin-bottom: 10px;
        }
        .qm-q-num {
          font-weight: 800;
          font-size: 0.78rem;
          text-transform: uppercase;
          letter-spacing: 0.04em;
          color: #38bdf8;
          padding: 3px 10px;
          background: rgba(56, 189, 248, 0.1);
          border-radius: 6px;
        }
        .qm-q-actions {
          display: flex;
          gap: 6px;
        }
        .qm-action-btn {
          display: inline-flex;
          align-items: center;
          gap: 4px;
          padding: 4px 10px;
          border-radius: 7px;
          font-size: 0.76rem;
          font-weight: 600;
          cursor: pointer;
          border: 1px solid transparent;
          transition: all 0.15s;
        }
        .qm-action-edit {
          background: rgba(148, 163, 184, 0.08);
          color: #94a3b8;
          border-color: rgba(148, 163, 184, 0.15);
        }
        .qm-action-edit:hover {
          background: rgba(56, 189, 248, 0.1);
          color: #38bdf8;
          border-color: rgba(56, 189, 248, 0.3);
        }
        .qm-action-cancel {
          background: rgba(239, 68, 68, 0.08);
          color: #f87171;
          border-color: rgba(239, 68, 68, 0.2);
        }
        .qm-action-cancel:hover {
          background: rgba(239, 68, 68, 0.15);
        }
        .qm-action-save {
          background: rgba(34, 197, 94, 0.12);
          color: #4ade80;
          border-color: rgba(34, 197, 94, 0.25);
        }
        .qm-action-save:hover {
          background: rgba(34, 197, 94, 0.2);
        }

        /* Question text */
        .qm-q-text {
          font-size: 0.94rem;
          line-height: 1.65;
          color: #e2e8f0;
          margin: 0 0 14px;
        }
        .qm-edit-textarea {
          width: 100%;
          padding: 10px 14px;
          border: 2px solid rgba(56, 189, 248, 0.25);
          border-radius: 10px;
          background: rgba(15, 23, 42, 0.6);
          color: #f1f5f9;
          font-size: 0.92rem;
          font-family: inherit;
          line-height: 1.6;
          resize: vertical;
          outline: none;
          transition: border-color 0.2s;
          margin-bottom: 14px;
        }
        .qm-edit-textarea:focus {
          border-color: #38bdf8;
        }

        /* ── Options ── */
        .qm-options {
          display: flex;
          flex-direction: column;
          gap: 7px;
        }
        .qm-option {
          display: flex;
          align-items: center;
          gap: 10px;
          padding: 10px 14px;
          border: 1px solid rgba(148, 163, 184, 0.1);
          border-radius: 10px;
          background: rgba(15, 23, 42, 0.35);
          transition: all 0.15s;
        }
        .qm-option:hover {
          border-color: rgba(148, 163, 184, 0.2);
        }
        .qm-option-correct {
          background: rgba(34, 197, 94, 0.06);
          border-color: rgba(34, 197, 94, 0.22);
        }
        .qm-option-correct:hover {
          border-color: rgba(34, 197, 94, 0.35);
        }
        .qm-option-editable {
          padding: 6px 10px;
        }
        .qm-option-letter {
          display: flex;
          align-items: center;
          justify-content: center;
          min-width: 28px; height: 28px;
          border-radius: 7px;
          font-weight: 800;
          font-size: 0.78rem;
          background: rgba(56, 189, 248, 0.1);
          color: #38bdf8;
          flex-shrink: 0;
        }
        .qm-letter-correct {
          background: rgba(34, 197, 94, 0.15);
          color: #22c55e;
        }
        .qm-option-text {
          flex: 1;
          font-size: 0.9rem;
          color: #cbd5e1;
          line-height: 1.5;
        }
        .qm-option-correct .qm-option-text {
          color: #86efac;
        }
        .qm-option-input {
          flex: 1;
          padding: 7px 12px;
          border: 2px solid rgba(56, 189, 248, 0.2);
          border-radius: 8px;
          background: rgba(15, 23, 42, 0.6);
          color: #f1f5f9;
          font-size: 0.88rem;
          font-family: inherit;
          outline: none;
          transition: border-color 0.2s;
        }
        .qm-option-input:focus {
          border-color: #38bdf8;
        }
        .qm-correct-icon {
          color: #22c55e;
          flex-shrink: 0;
        }

        /* Radio button for correct answer selection */
        .qm-radio-label {
          display: flex;
          align-items: center;
          cursor: pointer;
          flex-shrink: 0;
        }
        .qm-radio-label input[type="radio"] {
          display: none;
        }
        .qm-radio-dot {
          width: 20px; height: 20px;
          border-radius: 50%;
          border: 2px solid rgba(148, 163, 184, 0.3);
          background: rgba(15, 23, 42, 0.5);
          transition: all 0.15s;
          position: relative;
        }
        .qm-radio-dot::after {
          content: '';
          position: absolute;
          top: 50%; left: 50%;
          transform: translate(-50%, -50%);
          width: 8px; height: 8px;
          border-radius: 50%;
          background: transparent;
          transition: background 0.15s;
        }
        .qm-radio-active {
          border-color: #22c55e;
          background: rgba(34, 197, 94, 0.1);
        }
        .qm-radio-active::after {
          background: #22c55e;
        }
        .qm-radio-label:hover .qm-radio-dot:not(.qm-radio-active) {
          border-color: rgba(148, 163, 184, 0.5);
        }

        /* ── Footer ── */
        .quiz-modal-footer {
          display: flex;
          align-items: center;
          justify-content: space-between;
          gap: 10px;
          padding: 16px 28px;
          border-top: 1px solid rgba(56, 189, 248, 0.12);
          background: rgba(15, 23, 42, 0.45);
          border-radius: 0 0 18px 18px;
        }
        .qm-footer-left {
          display: flex;
          gap: 8px;
        }
        .qm-footer-right {
          display: flex;
          flex-wrap: wrap;
          gap: 8px;
          justify-content: flex-end;
        }
        .qm-footer-btn {
          display: inline-flex;
          align-items: center;
          gap: 6px;
          padding: 8px 16px;
          border-radius: 9px;
          font-size: 0.82rem;
          font-weight: 600;
          cursor: pointer;
          border: none;
          transition: all 0.18s ease;
          font-family: inherit;
        }
        .qm-footer-btn:disabled {
          opacity: 0.4;
          cursor: not-allowed;
        }
        .qm-btn-close {
          background: rgba(148, 163, 184, 0.08);
          border: 1px solid rgba(148, 163, 184, 0.18);
          color: #94a3b8;
        }
        .qm-btn-close:hover {
          background: rgba(148, 163, 184, 0.15);
          color: #e2e8f0;
        }
        .qm-btn-download {
          background: rgba(148, 163, 184, 0.08);
          border: 1px solid rgba(148, 163, 184, 0.18);
          color: #94a3b8;
        }
        .qm-btn-download:hover:not(:disabled) {
          background: rgba(56, 189, 248, 0.08);
          border-color: rgba(56, 189, 248, 0.25);
          color: #38bdf8;
        }
        .qm-btn-export {
          background: linear-gradient(135deg, #0ea5e9 0%, #0284c7 100%);
          color: white;
        }
        .qm-btn-export:hover:not(:disabled) {
          background: linear-gradient(135deg, #38bdf8 0%, #0ea5e9 100%);
          transform: translateY(-1px);
          box-shadow: 0 3px 12px rgba(56, 189, 248, 0.35);
        }
        .qm-btn-deploy {
          background: linear-gradient(135deg, #3b82f6 0%, #8b5cf6 100%);
          color: white;
        }
        .qm-btn-deploy:hover:not(:disabled) {
          transform: translateY(-1px);
          box-shadow: 0 3px 12px rgba(99, 102, 241, 0.35);
        }
        .qm-btn-save {
          background: rgba(129, 140, 248, 0.12);
          border: 1px solid rgba(129, 140, 248, 0.25);
          color: #a5b4fc;
        }
        .qm-btn-save:hover:not(:disabled) {
          background: rgba(129, 140, 248, 0.2);
          border-color: rgba(129, 140, 248, 0.4);
          transform: translateY(-1px);
        }
        .qm-btn-save-ok {
          background: rgba(34, 197, 94, 0.12) !important;
          border-color: rgba(34, 197, 94, 0.3) !important;
          color: #4ade80 !important;
        }

        /* ── Scrollbar ── */
        .quiz-modal-body::-webkit-scrollbar { width: 6px; }
        .quiz-modal-body::-webkit-scrollbar-track { background: transparent; }
        .quiz-modal-body::-webkit-scrollbar-thumb {
          background: rgba(56, 189, 248, 0.15);
          border-radius: 3px;
        }
        .quiz-modal-body::-webkit-scrollbar-thumb:hover {
          background: rgba(56, 189, 248, 0.3);
        }

        /* ── Responsive ── */
        @media (max-width: 768px) {
          .quiz-modal {
            max-width: 100%;
            max-height: 100vh;
            border-radius: 0;
          }
          .quiz-modal-header {
            padding: 16px 18px;
            border-radius: 0;
          }
          .quiz-modal-body {
            padding: 16px 18px;
          }
          .quiz-modal-footer {
            flex-direction: column;
            padding: 14px 18px;
            border-radius: 0;
          }
          .qm-footer-left, .qm-footer-right {
            width: 100%;
            justify-content: center;
          }
          .qm-header-tags { gap: 4px; }
        }

        /* Edit Topics Modal Styles */
        .edit-topics-overlay {
          z-index: 1100; /* Higher than topic modal */
        }

        .edit-topics-modal {
          background: rgba(22, 33, 55, 0.97);
          backdrop-filter: blur(20px);
          border: 1px solid rgba(56, 189, 248, 0.25);
          border-radius: 16px;
          width: 100%;
          max-width: 750px;
          max-height: 85vh;
          display: flex;
          flex-direction: column;
          box-shadow: 0 20px 60px rgba(0, 0, 0, 0.6), 0 0 40px rgba(56, 189, 248, 0.08), inset 0 1px 0 rgba(255, 255, 255, 0.05);
          animation: slideUp 0.3s ease;
        }

        .edit-topics-modal .modal-body {
          flex: 1;
          overflow-y: auto;
          padding: 20px 24px;
          padding-bottom: 40px;
        }

        .edit-topics-body {
          display: flex;
          flex-direction: column;
          gap: 20px;
          overflow: visible;
        }

        .add-topic-section label,
        .edit-topics-list label {
          display: block;
          font-weight: 600;
          color: #e2e8f0;
          margin-bottom: 10px;
          font-size: 0.9rem;
        }

        .add-topic-input-group {
          display: flex;
          gap: 10px;
        }

        .add-topic-input {
          flex: 1;
          padding: 12px 16px;
          border: 2px solid rgba(56, 189, 248, 0.22);
          border-radius: 10px;
          font-size: 0.9rem;
          transition: all 0.2s ease;
          color: #e2e8f0;
          background: rgba(22, 33, 55, 0.7);
        }

        .add-topic-input:focus {
          outline: none;
          border-color: #38bdf8;
          box-shadow: 0 0 0 4px rgba(56, 189, 248, 0.12);
        }

        .btn-add-topic {
          display: flex;
          align-items: center;
          gap: 6px;
          padding: 0 20px;
          background: linear-gradient(135deg, #10b981 0%, #059669 100%);
          border: none;
          border-radius: 10px;
          color: white;
          font-weight: 600;
          font-size: 0.9rem;
          cursor: pointer;
          transition: all 0.2s ease;
        }

        .btn-add-topic:hover:not(:disabled) {
          background: linear-gradient(135deg, #059669 0%, #047857 100%);
          transform: translateY(-1px);
        }

        .btn-add-topic:disabled {
          background: rgba(100, 116, 139, 0.3);
          cursor: not-allowed;
        }

        .no-topics-message {
          display: flex;
          align-items: center;
          justify-content: center;
          gap: 10px;
          padding: 40px 20px;
          background: rgba(22, 33, 55, 0.5);
          border: 2px dashed rgba(56, 189, 248, 0.22);
          border-radius: 12px;
          color: #64748b;
          font-size: 0.9rem;
        }

        .topics-edit-grid {
          display: flex;
          flex-direction: column;
          gap: 8px;
        }

        .topic-edit-item {
          display: flex;
          align-items: center;
          gap: 12px;
          padding: 12px 16px;
          background: rgba(22, 33, 55, 0.55);
          border: 1px solid rgba(56, 189, 248, 0.15);
          border-radius: 10px;
          transition: all 0.2s ease;
        }

        .topic-edit-item:hover {
          background: rgba(56, 189, 248, 0.08);
          border-color: rgba(56, 189, 248, 0.3);
        }

        .topic-number {
          display: flex;
          align-items: center;
          justify-content: center;
          min-width: 28px;
          height: 28px;
          background: linear-gradient(135deg, #38bdf8 0%, #0ea5e9 100%);
          color: white;
          border-radius: 8px;
          font-size: 0.8rem;
          font-weight: 700;
        }

        .topic-name {
          flex: 1;
          font-size: 0.9rem;
          color: #e2e8f0;
        }

        .topic-actions {
          display: flex;
          gap: 6px;
        }

        .btn-edit-topic,
        .btn-delete-topic {
          display: flex;
          align-items: center;
          justify-content: center;
          gap: 6px;
          padding: 8px 12px;
          min-width: 70px;
          height: 32px;
          border: 1px solid rgba(56, 189, 248, 0.18);
          border-radius: 8px;
          background: rgba(22, 33, 55, 0.65);
          color: #94a3b8;
          font-size: 0.8rem;
          font-weight: 500;
          cursor: pointer;
          transition: all 0.2s ease;
        }

        .btn-edit-topic:hover {
          background: rgba(56, 189, 248, 0.12);
          border-color: #38bdf8;
          color: #38bdf8;
        }

        .btn-delete-topic:hover {
          background: rgba(248, 113, 113, 0.12);
          border-color: rgba(248, 113, 113, 0.4);
          color: #f87171;
        }

        .topic-edit-inline {
          display: flex;
          align-items: center;
          gap: 8px;
          flex: 1;
        }

        .topic-edit-input {
          flex: 1;
          padding: 8px 12px;
          border: 2px solid #38bdf8;
          border-radius: 8px;
          font-size: 0.9rem;
          outline: none;
          color: #e2e8f0;
          background: rgba(22, 33, 55, 0.7);
        }

        .btn-save-edit,
        .btn-cancel-edit {
          display: flex;
          align-items: center;
          justify-content: center;
          gap: 6px;
          padding: 8px 12px;
          min-width: 70px;
          height: 32px;
          border: 1px solid rgba(56, 189, 248, 0.1);
          border-radius: 8px;
          font-size: 0.8rem;
          font-weight: 500;
          cursor: pointer;
          transition: all 0.2s ease;
        }

        .btn-save-edit {
          background: #10b981;
          border-color: #10b981;
          color: white;
        }

        .btn-save-edit:hover {
          background: #059669;
          border-color: #059669;
        }

        .btn-cancel-edit {
          background: rgba(15, 23, 42, 0.6);
          color: #94a3b8;
        }

        .btn-cancel-edit:hover {
          background: rgba(56, 189, 248, 0.08);
          border-color: rgba(56, 189, 248, 0.2);
          color: #e2e8f0;
        }

        .btn-modal-edit-topics {
          display: inline-flex;
          align-items: center;
          gap: 6px;
          padding: 6px 12px;
          border: 1px solid rgba(251, 191, 36, 0.2);
          border-radius: 8px;
          background: rgba(251, 191, 36, 0.06);
          color: #fbbf24;
          font-size: 0.8rem;
          font-weight: 500;
          cursor: pointer;
          transition: all 0.2s ease;
        }

        .btn-modal-edit-topics:hover {
          background: rgba(251, 191, 36, 0.1);
          border-color: rgba(251, 191, 36, 0.3);
          color: #f59e0b;
        }

        .modal-topics-toolbar {
          display: flex;
          gap: 8px;
          margin-bottom: 12px;
        }

        /* ===== Responsive: Tablet ===== */
        @media (max-width: 768px) {
          .topic-modal,
          .quiz-modal,
          .edit-topics-modal {
            max-width: 95%;
            max-height: 90vh;
            margin: 0.5rem;
            border-radius: 14px;
          }

          .modal-header,
          .quiz-modal-header {
            padding: 14px 16px;
          }
          .modal-header h3,
          .quiz-modal-header h3 {
            font-size: 1rem;
          }
          .modal-close {
            padding: 0 10px;
            height: 36px;
            min-width: 70px;
            font-size: 0.82rem;
          }

          .topic-source-selector {
            padding: 12px 16px;
            gap: 6px;
          }
          .source-tab {
            padding: 10px 12px;
            font-size: 0.82rem;
          }

          .modal-body,
          .quiz-modal-body {
            padding: 14px 16px;
          }

          .modal-footer,
          .quiz-modal-footer {
            padding: 12px 16px;
            flex-wrap: wrap;
            gap: 8px;
          }
          .modal-footer .btn,
          .quiz-modal-footer .btn {
            padding: 8px 16px;
            font-size: 0.84rem;
            flex: 1;
            justify-content: center;
            min-width: 0;
          }

          .modal-doc-header {
            padding: 12px 14px;
            gap: 10px;
          }
          .modal-doc-info { gap: 10px; }
          .modal-doc-name { font-size: 0.85rem; }

          .modal-topic-tag {
            padding: 6px 12px;
            font-size: 0.8rem;
          }

          .quiz-modal .quiz-question {
            padding: 14px;
          }
          .quiz-modal .question-text { font-size: 0.9rem; }
          .quiz-modal .option-label {
            padding: 8px 12px;
          }
          .quiz-modal .edit-option {
            flex-wrap: wrap;
            gap: 6px;
          }

          .quiz-preview-card {
            flex-direction: column;
            align-items: flex-start;
            gap: 12px;
          }
          .quiz-preview-actions {
            width: 100%;
            flex-wrap: wrap;
          }
          .quiz-preview-actions .btn {
            flex: 1;
            justify-content: center;
          }
          .quiz-preview-meta {
            max-width: 100%;
          }

          .edit-topics-modal .modal-body {
            padding: 14px 16px;
          }
          .add-topic-input-group {
            flex-direction: column;
          }
          .btn-add-topic {
            padding: 10px 20px;
            justify-content: center;
          }
          .topic-edit-item {
            padding: 10px 12px;
            gap: 8px;
          }
          .topic-actions {
            flex-wrap: wrap;
          }
          .topic-edit-inline {
            flex-wrap: wrap;
          }
        }

        /* ===== Responsive: Small Mobile ===== */
        @media (max-width: 480px) {
          .topic-modal,
          .quiz-modal,
          .edit-topics-modal {
            max-width: 100%;
            max-height: 95vh;
            margin: 0;
            border-radius: 12px 12px 0 0;
          }

          .modal-header,
          .quiz-modal-header {
            padding: 12px 14px;
          }
          .modal-header h3,
          .quiz-modal-header h3 {
            font-size: 0.92rem;
            gap: 8px;
          }
          .modal-close span { display: none; }
          .modal-close {
            min-width: 36px;
            width: 36px;
            height: 36px;
            padding: 0;
            border-radius: 10px;
          }

          .quiz-modal-header-info { gap: 6px; }
          .quiz-count { font-size: 0.72rem; padding: 3px 8px; }

          .topic-source-selector {
            flex-direction: column;
            padding: 10px 14px;
          }
          .source-tab {
            padding: 10px;
            font-size: 0.8rem;
          }

          .modal-body,
          .quiz-modal-body {
            padding: 12px 14px;
          }
          .modal-empty-state { padding: 32px 16px; }
          .modal-selected-summary {
            padding: 10px 12px;
            font-size: 0.82rem;
          }

          .modal-footer,
          .quiz-modal-footer {
            padding: 10px 14px;
            flex-direction: column;
          }
          .modal-footer .btn,
          .quiz-modal-footer .btn {
            width: 100%;
            justify-content: center;
          }

          .modal-doc-header {
            padding: 10px 12px;
            gap: 8px;
          }
          .modal-doc-topics { padding: 12px; }
          .modal-topics-grid { gap: 6px; }
          .modal-topic-tag {
            padding: 6px 10px;
            font-size: 0.78rem;
          }

          .quiz-modal .quiz-question { padding: 12px; border-radius: 10px; }
          .quiz-modal .question-header { margin-bottom: 8px; }
          .quiz-modal .question-text { font-size: 0.85rem; }
          .quiz-modal .option-label { padding: 8px 10px; font-size: 0.84rem; }
          .quiz-modal .question-explanation { padding: 10px; font-size: 0.8rem; }

          .quiz-preview-card { padding: 12px 14px; }
          .quiz-preview-title { font-size: 0.88rem; }

          .topic-edit-item {
            flex-direction: column;
            align-items: stretch;
            gap: 8px;
          }
          .topic-number { align-self: flex-start; }
          .topic-actions {
            justify-content: flex-end;
          }
          .topic-edit-inline {
            flex-direction: column;
            gap: 6px;
          }
          .btn-save-edit,
          .btn-cancel-edit {
            flex: 1;
          }
          .no-topics-message {
            padding: 24px 16px;
            font-size: 0.82rem;
          }
        }

        /* ===================================================================
           SAVE-QUIZ MODAL (Lưu vào Kho Đề Thi)
        =================================================================== */
        .sqm-overlay {
          position: fixed;
          inset: 0;
          z-index: 10000;
          background: rgba(4, 6, 14, 0.72);
          backdrop-filter: blur(6px);
          -webkit-backdrop-filter: blur(6px);
          display: flex;
          align-items: center;
          justify-content: center;
          padding: 24px;
          animation: sqmFadeIn 0.18s ease-out;
        }
        @keyframes sqmFadeIn {
          from { opacity: 0; }
          to { opacity: 1; }
        }
        .sqm-modal {
          width: 100%;
          max-width: 520px;
          max-height: calc(100vh - 48px);
          overflow: hidden;
          display: flex;
          flex-direction: column;
          background: linear-gradient(180deg, #0f1424 0%, #0a0e1c 100%);
          border: 1px solid rgba(34, 211, 238, 0.18);
          border-radius: 16px;
          box-shadow:
            0 24px 60px -12px rgba(0, 0, 0, 0.7),
            0 0 0 1px rgba(255, 255, 255, 0.03) inset,
            0 0 40px rgba(34, 211, 238, 0.08);
          animation: sqmSlideUp 0.22s cubic-bezier(0.2, 0.9, 0.3, 1);
        }
        @keyframes sqmSlideUp {
          from { opacity: 0; transform: translateY(16px) scale(0.98); }
          to   { opacity: 1; transform: translateY(0) scale(1); }
        }
        .sqm-header {
          display: flex;
          align-items: center;
          gap: 14px;
          padding: 18px 20px;
          border-bottom: 1px solid rgba(148, 163, 184, 0.1);
          background: linear-gradient(180deg, rgba(34, 211, 238, 0.06) 0%, transparent 100%);
        }
        .sqm-header-icon {
          flex-shrink: 0;
          width: 40px;
          height: 40px;
          border-radius: 10px;
          display: flex;
          align-items: center;
          justify-content: center;
          background: linear-gradient(135deg, rgba(34, 211, 238, 0.18), rgba(56, 189, 248, 0.12));
          border: 1px solid rgba(34, 211, 238, 0.3);
          color: #22d3ee;
        }
        .sqm-header-text {
          flex: 1;
          min-width: 0;
        }
        .sqm-title {
          margin: 0;
          font-size: 1.02rem;
          font-weight: 600;
          color: #f1f5f9;
          letter-spacing: -0.01em;
        }
        .sqm-subtitle {
          margin: 2px 0 0 0;
          font-size: 0.78rem;
          color: #94a3b8;
          font-weight: 500;
        }
        .sqm-close {
          flex-shrink: 0;
          width: 32px;
          height: 32px;
          border-radius: 8px;
          background: transparent;
          border: 1px solid transparent;
          color: #94a3b8;
          cursor: pointer;
          display: flex;
          align-items: center;
          justify-content: center;
          transition: all 0.15s ease;
        }
        .sqm-close:hover:not(:disabled) {
          background: rgba(244, 63, 94, 0.1);
          border-color: rgba(244, 63, 94, 0.25);
          color: #fb7185;
        }
        .sqm-close:disabled {
          opacity: 0.4;
          cursor: not-allowed;
        }
        .sqm-body {
          padding: 20px;
          overflow-y: auto;
          display: flex;
          flex-direction: column;
          gap: 18px;
        }
        .sqm-body::-webkit-scrollbar { width: 6px; }
        .sqm-body::-webkit-scrollbar-thumb {
          background: rgba(148, 163, 184, 0.2);
          border-radius: 3px;
        }
        .sqm-field {
          display: flex;
          flex-direction: column;
          gap: 6px;
        }
        .sqm-label {
          font-size: 0.82rem;
          font-weight: 600;
          color: #cbd5e1;
          letter-spacing: 0.01em;
        }
        .sqm-required {
          color: #fb7185;
          margin-left: 2px;
        }
        .sqm-optional {
          color: #64748b;
          font-weight: 400;
          font-size: 0.74rem;
        }
        .sqm-input,
        .sqm-textarea {
          width: 100%;
          padding: 10px 12px;
          font-size: 0.88rem;
          color: #f1f5f9;
          background: rgba(15, 23, 42, 0.6);
          border: 1px solid rgba(148, 163, 184, 0.2);
          border-radius: 10px;
          outline: none;
          transition: all 0.15s ease;
          font-family: inherit;
          box-sizing: border-box;
        }
        .sqm-input::placeholder,
        .sqm-textarea::placeholder {
          color: #475569;
        }
        .sqm-input:focus,
        .sqm-textarea:focus {
          border-color: rgba(34, 211, 238, 0.55);
          background: rgba(15, 23, 42, 0.85);
          box-shadow: 0 0 0 3px rgba(34, 211, 238, 0.12);
        }
        .sqm-input:disabled,
        .sqm-textarea:disabled {
          opacity: 0.5;
          cursor: not-allowed;
        }
        .sqm-textarea {
          resize: vertical;
          min-height: 70px;
          line-height: 1.5;
        }
        .sqm-hint {
          font-size: 0.7rem;
          color: #64748b;
          text-align: right;
          font-variant-numeric: tabular-nums;
        }
        .sqm-tag-preview {
          display: flex;
          flex-wrap: wrap;
          gap: 6px;
          margin-top: 4px;
        }
        .sqm-tag-chip {
          display: inline-flex;
          align-items: center;
          padding: 3px 9px;
          font-size: 0.72rem;
          font-weight: 500;
          color: #67e8f9;
          background: rgba(34, 211, 238, 0.1);
          border: 1px solid rgba(34, 211, 238, 0.25);
          border-radius: 999px;
        }
        .sqm-error {
          display: flex;
          align-items: flex-start;
          gap: 8px;
          padding: 10px 12px;
          font-size: 0.8rem;
          color: #fca5a5;
          background: rgba(244, 63, 94, 0.08);
          border: 1px solid rgba(244, 63, 94, 0.25);
          border-radius: 10px;
          line-height: 1.4;
        }
        .sqm-error svg {
          flex-shrink: 0;
          margin-top: 1px;
        }
        .sqm-footer {
          display: flex;
          gap: 10px;
          justify-content: flex-end;
          padding: 14px 20px;
          border-top: 1px solid rgba(148, 163, 184, 0.1);
          background: rgba(8, 11, 24, 0.5);
        }
        .sqm-btn {
          display: inline-flex;
          align-items: center;
          gap: 6px;
          padding: 9px 18px;
          font-size: 0.85rem;
          font-weight: 600;
          border-radius: 10px;
          border: 1px solid transparent;
          cursor: pointer;
          transition: all 0.15s ease;
          font-family: inherit;
        }
        .sqm-btn:disabled {
          opacity: 0.5;
          cursor: not-allowed;
        }
        .sqm-btn-secondary {
          background: transparent;
          color: #cbd5e1;
          border-color: rgba(148, 163, 184, 0.25);
        }
        .sqm-btn-secondary:hover:not(:disabled) {
          background: rgba(148, 163, 184, 0.08);
          border-color: rgba(148, 163, 184, 0.4);
          color: #f1f5f9;
        }
        .sqm-btn-primary {
          color: #062a2f;
          background: linear-gradient(135deg, #22d3ee 0%, #38bdf8 100%);
          border-color: rgba(34, 211, 238, 0.5);
          box-shadow: 0 4px 16px -4px rgba(34, 211, 238, 0.5);
        }
        .sqm-btn-primary:hover:not(:disabled) {
          transform: translateY(-1px);
          box-shadow: 0 8px 22px -4px rgba(34, 211, 238, 0.6);
        }
        .sqm-btn-primary:active:not(:disabled) {
          transform: translateY(0);
        }
        @media (max-width: 600px) {
          .sqm-modal { max-width: 100%; }
          .sqm-header, .sqm-body, .sqm-footer { padding-left: 16px; padding-right: 16px; }
          .sqm-footer { flex-direction: column-reverse; }
          .sqm-btn { width: 100%; justify-content: center; }
        }

        /* ===================================================================
           Uploaded Files Table — professional layout matching Canvas panel
        =================================================================== */
        .document-rag-panel .files-section .section-header {
          display: flex;
          align-items: center;
          justify-content: space-between;
          gap: 12px;
          margin-bottom: 12px;
        }
        .document-rag-panel .files-section .section-header h3 {
          display: flex;
          align-items: center;
          gap: 10px;
          margin: 0;
          font-size: 1rem;
          color: #e2e8f0;
        }
        .document-rag-panel .files-section .section-actions {
          display: flex;
          gap: 8px;
        }
        .document-rag-panel .files-list {
          background: rgba(15, 23, 42, 0.5);
          border: 1px solid rgba(56, 189, 248, 0.15);
          border-radius: 10px;
          overflow-x: auto;
        }
        .document-rag-panel .rag-uploaded-files-table {
          width: 100%;
          border-collapse: collapse;
          table-layout: fixed;
          min-width: 720px;
        }
        .document-rag-panel .rag-uploaded-files-table th,
        .document-rag-panel .rag-uploaded-files-table td {
          padding: 14px 16px;
          text-align: left;
          border-bottom: 1px solid rgba(56, 189, 248, 0.08);
          vertical-align: middle;
          font-size: 0.88rem;
          color: #cbd5e1;
        }
        .document-rag-panel .rag-uploaded-files-table thead th {
          background: rgba(15, 23, 42, 0.7);
          color: #94a3b8;
          font-weight: 600;
          font-size: 0.75rem;
          text-transform: uppercase;
          letter-spacing: 0.5px;
          white-space: nowrap;
        }
        /* Column widths: name flexes; others fixed and balanced */
        .document-rag-panel .rag-uploaded-files-table col.col-name { width: auto; }
        .document-rag-panel .rag-uploaded-files-table col.col-size { width: 96px; }
        .document-rag-panel .rag-uploaded-files-table col.col-topics { width: 132px; }
        .document-rag-panel .rag-uploaded-files-table col.col-status { width: 158px; }
        .document-rag-panel .rag-uploaded-files-table col.col-actions { width: 156px; }
        .document-rag-panel .rag-uploaded-files-table th.actions-col,
        .document-rag-panel .rag-uploaded-files-table td.actions-cell {
          text-align: right;
        }
        /* Center-align pill columns so the header text lines up with the
           visible pill content (pills have inner padding, plain text doesn't,
           which would otherwise make headers look shifted to the left). */
        .document-rag-panel .rag-uploaded-files-table th:nth-child(2),
        .document-rag-panel .rag-uploaded-files-table td:nth-child(2),
        .document-rag-panel .rag-uploaded-files-table th:nth-child(3),
        .document-rag-panel .rag-uploaded-files-table td:nth-child(3),
        .document-rag-panel .rag-uploaded-files-table th:nth-child(4),
        .document-rag-panel .rag-uploaded-files-table td:nth-child(4) {
          text-align: center;
        }
        .document-rag-panel .rag-uploaded-files-table tbody tr:hover {
          background: rgba(56, 189, 248, 0.04);
        }
        .document-rag-panel .rag-uploaded-files-table tbody tr:last-child td {
          border-bottom: none;
        }
        .document-rag-panel .rag-uploaded-files-table .file-name {
          display: flex;
          align-items: center;
          gap: 10px;
          min-width: 0;
        }
        .document-rag-panel .rag-uploaded-files-table .file-name svg {
          color: #38bdf8;
          flex-shrink: 0;
        }
        .document-rag-panel .rag-uploaded-files-table .file-name span {
          color: #e2e8f0;
          font-weight: 600;
          overflow: hidden;
          text-overflow: ellipsis;
          white-space: nowrap;
          min-width: 0;
        }
        .document-rag-panel .rag-uploaded-files-table .file-size {
          color: #94a3b8;
          font-variant-numeric: tabular-nums;
          font-size: 0.85rem;
          white-space: nowrap;
        }
        .document-rag-panel .rag-uploaded-files-table .file-status {
          display: inline-flex;
          align-items: center;
          gap: 6px;
          padding: 5px 10px;
          border-radius: 999px;
          font-size: 0.78rem;
          font-weight: 600;
          white-space: nowrap;
          max-width: 100%;
          overflow: hidden;
          text-overflow: ellipsis;
        }
        .document-rag-panel .rag-uploaded-files-table .file-status .spin {
          animation: rag-spin 1s linear infinite;
        }
        @keyframes rag-spin {
          to { transform: rotate(360deg); }
        }
        .document-rag-panel .rag-uploaded-files-table .topic-count {
          display: inline-block;
          padding: 4px 10px;
          border-radius: 999px;
          background: rgba(34, 211, 238, 0.10);
          color: #67e8f9;
          font-size: 0.78rem;
          font-weight: 600;
          white-space: nowrap;
          max-width: 100%;
          overflow: hidden;
          text-overflow: ellipsis;
        }
        .document-rag-panel .rag-uploaded-files-table .topic-count.empty {
          background: rgba(100, 116, 139, 0.12);
          color: #94a3b8;
        }
        .document-rag-panel .rag-uploaded-files-table .topic-count.loading {
          display: inline-flex;
          align-items: center;
          gap: 6px;
          background: rgba(148, 163, 184, 0.12);
          color: #cbd5e1;
        }
        .document-rag-panel .rag-uploaded-files-table .topic-count.loading .spin {
          animation: rag-spin 1s linear infinite;
        }

        /* Icon-only action buttons (matches CanvasFilesPanel) */
        .document-rag-panel .rag-uploaded-files-table .action-buttons {
          display: inline-flex;
          flex-wrap: nowrap;
          gap: 6px;
          justify-content: flex-end;
          align-items: center;
        }
        .document-rag-panel .rag-uploaded-files-table .btn-action {
          display: inline-flex;
          align-items: center;
          justify-content: center;
          width: 34px;
          height: 34px;
          padding: 0;
          border-radius: 8px;
          border: 1px solid rgba(56, 189, 248, 0.25);
          background: rgba(15, 23, 42, 0.6);
          color: #cbd5e1;
          cursor: pointer;
          transition: all 0.15s ease;
          flex-shrink: 0;
        }
        .document-rag-panel .rag-uploaded-files-table .btn-action svg {
          flex-shrink: 0;
        }
        .document-rag-panel .rag-uploaded-files-table .btn-action:hover:not(:disabled) {
          background: rgba(56, 189, 248, 0.15);
          border-color: rgba(56, 189, 248, 0.5);
          color: #e0f2fe;
          transform: translateY(-1px);
        }
        .document-rag-panel .rag-uploaded-files-table .btn-action:disabled {
          opacity: 0.45;
          cursor: not-allowed;
        }
        .document-rag-panel .rag-uploaded-files-table .btn-action.btn-primary-action {
          background: linear-gradient(135deg, #38bdf8 0%, #0ea5e9 100%);
          color: #0b1120;
          border-color: rgba(56, 189, 248, 0.6);
          box-shadow: 0 2px 8px rgba(56, 189, 248, 0.25);
        }
        .document-rag-panel .rag-uploaded-files-table .btn-action.btn-primary-action:hover:not(:disabled) {
          color: #ffffff;
          background: linear-gradient(135deg, #0ea5e9 0%, #0284c7 100%);
        }
        .document-rag-panel .rag-uploaded-files-table .btn-action.warning {
          color: #fca5a5;
          border-color: rgba(248, 113, 113, 0.35);
          background: rgba(127, 29, 29, 0.18);
        }
        .document-rag-panel .rag-uploaded-files-table .btn-action.warning:hover:not(:disabled) {
          background: rgba(248, 113, 113, 0.18);
          color: #fecaca;
          border-color: rgba(248, 113, 113, 0.6);
        }

        /* Compact view on narrow widths */
        @media (max-width: 1024px) {
          .document-rag-panel .rag-uploaded-files-table {
            min-width: 600px;
          }
          .document-rag-panel .rag-uploaded-files-table col.col-size { width: 0; }
          .document-rag-panel .rag-uploaded-files-table th:nth-child(2),
          .document-rag-panel .rag-uploaded-files-table td:nth-child(2) { display: none; }
        }
        @media (max-width: 720px) {
          .document-rag-panel .rag-uploaded-files-table col.col-topics { width: 0; }
          .document-rag-panel .rag-uploaded-files-table th:nth-child(3),
          .document-rag-panel .rag-uploaded-files-table td:nth-child(3) { display: none; }
        }
      `}</style>

      {/* Quiz generation progress modal */}
      <JobProgressModal
        job={quizJob.job}
        visible={quizJob.showProgress}
        title="Đang tạo quiz..."
        queuedWarning={quizJob.queuedWarning}
        onCancel={quizJob.cancel}
        onClose={quizJob.reset}
      />
    </div>
  );
};

export default DocumentRAGPanel;
