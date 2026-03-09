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
  checkOllamaStatus,
  listUploadedFiles,
  exportQuizToQTI,
  getDocumentTopics,
  updateDocumentTopics,
  listIndexedDocuments,
  getLLMProviderInfo,
  setLLMProvider,
  asyncUploadAndIndex,
  asyncGenerateQuiz,
  type RAGIndexStats,
  type RAGUploadedFile,
  type OllamaStatus,
  type QuizQuestion,
  type TopicSuggestion,
  type LLMProviderInfo,
} from '../api/documentRag';
import { getJob, TERMINAL_STATUSES, type JobOut } from '../api/jobs';
import { useAsyncJob } from '../hooks/useAsyncJob';
import JobProgressModal from './JobProgressModal';
import {
  listIndexedCanvasDocuments,
  getCanvasDocumentTopics,
  updateCanvasDocumentTopics,
  asyncCanvasGenerateQuiz,
} from '../api/canvasRag';
import CanvasImportModal from './CanvasImportModal';
import { useModelConfig } from '../context/ModelConfigContext';

// Indexed document info
interface IndexedDocument {
  filename: string;
  original_filename: string;
  topic_count: number;
  indexed_at: string;
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
  const [generatedQuiz, setGeneratedQuiz] = useState<QuizQuestion[]>([]);
  const [isGeneratingQuiz, setIsGeneratingQuiz] = useState(false);
  const [quizError, setQuizError] = useState<string | null>(null);
  const [editingQuestionIndex, setEditingQuestionIndex] = useState<number | null>(null);
  const [editingQuestion, setEditingQuestion] = useState<QuizQuestion | null>(null);
  const [isExporting, setIsExporting] = useState(false);
  
  // Document and Topic selection states
  const [indexedDocuments, setIndexedDocuments] = useState<IndexedDocument[]>([]);
  const [selectedDocuments, setSelectedDocuments] = useState<string[]>([]);
  const [topicsCache, setTopicsCache] = useState<Record<string, TopicSuggestion[]>>({});
  const [topicsByDocument, setTopicsByDocument] = useState<Record<string, TopicSuggestion[]>>({});
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
  const [ollamaStatus, setOllamaStatus] = useState<OllamaStatus | null>(null);
  const [uploadedFiles, setUploadedFiles] = useState<RAGUploadedFile[]>([]);
  const [uploadedPage, setUploadedPage] = useState(1);
  const [uploadedPages, setUploadedPages] = useState(1);
  const [uploadedTotal, setUploadedTotal] = useState(0);
  const [indexedPage, setIndexedPage] = useState(1);
  const [indexedPages, setIndexedPages] = useState(1);
  const [indexedTotal, setIndexedTotal] = useState(0);
  
  // Messages
  const [uploadMessage, setUploadMessage] = useState<{ type: 'success' | 'error' | 'info'; text: string } | null>(null);

  
  // Model config (admin filtering)
  const { showProviderSwitch, isProviderEnabled } = useModelConfig();

  // LLM Provider states
  const [llmProviderInfo, setLlmProviderInfo] = useState<LLMProviderInfo | null>(null);
  const [isSwitchingProvider, setIsSwitchingProvider] = useState(false);
  const [providerMessage, setProviderMessage] = useState<{ type: 'success' | 'error'; text: string } | null>(null);
  
  const fileInputRef = useRef<HTMLInputElement>(null);

  // Load initial data
  useEffect(() => {
    loadIndexStats();
    loadOllamaStatus();
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
      const r = job.result as { success?: boolean; questions?: QuizQuestion[]; error?: string };
      if (r.success && r.questions && r.questions.length > 0) {
        setGeneratedQuiz(r.questions);
        setShowQuizModal(true);
      } else {
        setQuizError(r.error || 'Không thể tạo quiz. Hãy thử lại với chủ đề khác.');
      }
      setIsGeneratingQuiz(false);
      quizJob.reset();
    } else if (job.status === 'FAILED') {
      setQuizError(job.error_message || 'Lỗi khi tạo quiz.');
      setIsGeneratingQuiz(false);
      quizJob.reset();
    } else if (job.status === 'CANCELED') {
      setIsGeneratingQuiz(false);
      quizJob.reset();
    }
  }, [quizJob.job?.status]);

  // Listen for canvas topics updates from CanvasFilesPanel
  useEffect(() => {
    const handleCanvasTopicsUpdated = () => {
      console.log('Canvas topics updated event received, reloading...');
      loadCanvasIndexedDocuments();
      // Clear canvas topics cache to force reload
      setCanvasTopicsCache({});
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
      console.log('Canvas indexed documents response:', response);
      if (response.success && response.documents) {
        const docs: IndexedDocument[] = response.documents.map(d => ({
          filename: d.filename,
          original_filename: d.original_filename || d.filename,
          topic_count: d.topic_count,
          indexed_at: d.indexed_at,
        }));
        setCanvasIndexedDocuments(docs);
        console.log('Set canvasIndexedDocuments:', docs.length, 'documents');
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

  // Handle LLM provider switch
  const handleSwitchProvider = async (provider: 'ollama' | 'groq') => {
    if (isSwitchingProvider) return;
    
    setIsSwitchingProvider(true);
    setProviderMessage(null);
    
    try {
      const response = await setLLMProvider({ provider });
      
      if (response.success) {
        setProviderMessage({
          type: 'success',
          text: `Đã chuyển sang ${provider === 'groq' ? 'Groq Cloud' : 'Ollama'} thành công!`
        });
        // Reload provider info and status
        await loadLLMProviderInfo();
        await loadOllamaStatus();
      } else {
        setProviderMessage({
          type: 'error',
          text: response.error || `Không thể chuyển sang ${provider}`
        });
      }
    } catch (error) {
      console.error('Error switching provider:', error);
      setProviderMessage({
        type: 'error',
        text: `Lỗi khi chuyển mô hình AI: ${error}`
      });
    } finally {
      setIsSwitchingProvider(false);
      // Clear message after 5 seconds
      setTimeout(() => setProviderMessage(null), 5000);
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
    } catch (error) {
      console.error('Error loading indexed documents:', error);
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

  const loadOllamaStatus = async () => {
    try {
      const status = await checkOllamaStatus();
      setOllamaStatus(status);
    } catch (error) {
      console.error('Error checking Ollama:', error);
      setOllamaStatus({
        connected: false,
        message: 'Không thể kết nối đến Ollama',
        error: String(error),
      });
    }
  };

  const loadUploadedFiles = async (page?: number) => {
    try {
      const p = page ?? uploadedPage;
      const response = await listUploadedFiles(p);
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

  // Modal - Toggle document selection
  const toggleDocumentInModal = async (filename: string) => {
    const isCurrentlySelected = tempSelectedDocuments.includes(filename);
    
    if (isCurrentlySelected) {
      // Remove document and its selected topics
      setTempSelectedDocuments(prev => prev.filter(f => f !== filename));
      setTempSelectedTopics(st => st.filter(t => t.documentFilename !== filename));
      setTempTopicsByDocument(prev => {
        const updated = { ...prev };
        delete updated[filename];
        return updated;
      });
    } else {
      // Add document
      setTempSelectedDocuments(prev => [...prev, filename]);
      
      // Auto-load topics for this document based on source
      const cache = topicSource === 'canvas' ? canvasTopicsCache : topicsCache;
      
      if (!cache[filename]) {
        try {
          // Use appropriate API based on source
          const response = topicSource === 'canvas' 
            ? await getCanvasDocumentTopics(filename)
            : await getDocumentTopics(filename);
          
          if (response.success && response.topics) {
            const topics: TopicSuggestion[] = response.topics.map((name, idx) => ({
              name,
              relevance_score: 1 - (idx * 0.05),
              description: ''
            }));
            
            // Update appropriate cache
            if (topicSource === 'canvas') {
              setCanvasTopicsCache(prev => ({ ...prev, [filename]: topics }));
            } else {
              setTopicsCache(prev => ({ ...prev, [filename]: topics }));
            }
            setTempTopicsByDocument(prev => ({ ...prev, [filename]: topics }));
          }
        } catch (error) {
          console.error('Error loading topics for document:', error);
        }
      } else {
        setTempTopicsByDocument(prev => ({ ...prev, [filename]: cache[filename] }));
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
  const openEditTopicsModal = (filename: string) => {
    // Get topics from appropriate cache based on topic source
    const docTopics = topicSource === 'canvas'
      ? (tempTopicsByDocument[filename] || canvasTopicsCache[filename] || [])
      : (tempTopicsByDocument[filename] || topicsCache[filename] || []);
    setEditingDocumentFilename(filename);
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
        }
        
        setTempTopicsByDocument(prev => ({ ...prev, [editingDocumentFilename]: updatedTopics }));
        setTopicsByDocument(prev => ({ ...prev, [editingDocumentFilename]: updatedTopics }));
        
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
    if (!window.confirm('Bạn có chắc muốn xóa toàn bộ dữ liệu đã xử lý? Hành động này không thể hoàn tác.')) {
      return;
    }

    setIsResetting(true);

    try {
      const response = await resetRAGIndex();
      if (response.success) {
        setUploadMessage({ type: 'success', text: 'Đã xóa dữ liệu thành công' });
        setGeneratedQuiz([]);
        await loadIndexStats();
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

  // Quiz generation handler
  const handleGenerateQuiz = async () => {
    // Build topics list from selectedTopics or quizTopic
    const topicsList: string[] = selectedTopics.length > 0 
      ? selectedTopics.map(t => t.topic)
      : quizTopic.trim() ? [quizTopic.trim()] : [];
    
    if (topicsList.length === 0) {
      setQuizError('Vui lòng chọn chủ đề quiz hoặc nhập chủ đề');
      return;
    }

    setIsGeneratingQuiz(true);
    setQuizError(null);
    setGeneratedQuiz([]);
    setEditingQuestionIndex(null);
    setEditingQuestion(null);

    // Derive selected_documents from topics' source documents (not from ticked checkboxes)
    const docsFromTopics = selectedTopics.length > 0
      ? [...new Set(selectedTopics.map(t => t.documentFilename))]
      : undefined;

    const quizRequest = {
      topics: topicsList,
      num_questions: numQuestions,
      difficulty: quizDifficulty,
      language: quizLanguage,
      selected_documents: docsFromTopics,
    };

    try {
      if (topicSource === 'canvas') {
        // Canvas quiz — async via Celery
        await quizJob.startJob(() => asyncCanvasGenerateQuiz(quizRequest));
        // Result handled by useEffect on quizJob.job.status
      } else {
        // Document RAG quiz — async via Celery
        await quizJob.startJob(() => asyncGenerateQuiz(quizRequest));
        // Result handled by useEffect on quizJob.job.status
      }
    } catch (error) {
      console.error('Quiz generation error:', error);
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
            {showProviderSwitch ? (
              <div className="provider-dropdown-wrapper">
                <select
                  className="provider-dropdown-inline"
                  value={llmProviderInfo?.current_provider || 'ollama'}
                  onChange={(e) => handleSwitchProvider(e.target.value as 'ollama' | 'groq')}
                  disabled={isSwitchingProvider}
                >
                  {isProviderEnabled('ollama') && <option value="ollama">🖥️ Ollama</option>}
                  {isProviderEnabled('groq') && (
                    <option value="groq" disabled={!llmProviderInfo?.groq_configured}>
                      ☁️ Groq {!llmProviderInfo?.groq_configured ? '(N/A)' : ''}
                    </option>
                  )}
                </select>
                {isSwitchingProvider && (
                  <Loader2 size={12} className="spin provider-dropdown-loading" />
                )}
              </div>
            ) : (
              <span className="rag-chip-text">
                {(llmProviderInfo?.current_provider || 'ollama') === 'groq' ? '⚡ Groq' : '🖥️ Ollama'}
              </span>
            )}
          </div>
          <div className="rag-chip-divider" />
          <div className={`rag-chip rag-chip-model ${ollamaStatus?.connected ? 'connected' : 'disconnected'}`}>
            {ollamaStatus?.connected ? (
              <>
                <CheckCircle size={12} className="rag-chip-status-icon" />
                <span className="rag-chip-model-name">{llmProviderInfo?.current_model || ollamaStatus.model || 'Sẵn sàng'}</span>
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
            loadOllamaStatus();
            loadUploadedFiles();
            loadLLMProviderInfo();
          }}
          title="Làm mới trạng thái"
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
                <button
                  className="btn btn-primary btn-upload-main"
                  onClick={handleUploadAndIndex}
                  disabled={selectedFiles.length === 0 || isUploading || selectedFiles.every(f => f.status !== 'waiting')}
                >
                  {isUploading ? (
                    <>
                      <Loader2 size={16} className="spin" />
                      Đang xử lý...
                    </>
                  ) : (
                    <>
                      <Database size={16} />
                      Tải lên & Xử lý {selectedFiles.filter(f => f.status === 'waiting').length > 0 && 
                        `(${selectedFiles.filter(f => f.status === 'waiting').length} file)`}
                    </>
                  )}
                </button>

                <button
                  className="btn btn-outline-danger btn-reset"
                  onClick={handleResetIndex}
                  disabled={isResetting || (indexStats?.total_documents ?? 0) === 0}
                  title="Xóa toàn bộ dữ liệu đã xử lý"
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

        {/* Provider Switch Message */}
        {providerMessage && (
          <div className={`message provider-message ${providerMessage.type}`}>
            {providerMessage.type === 'success' && <CheckCircle size={16} />}
            {providerMessage.type === 'error' && <AlertCircle size={16} />}
            {providerMessage.text}
          </div>
        )}

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
                    {[3, 5, 7, 10, 15, 20, 30, 40, 50].map(n => (
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

              <button
                className="btn btn-primary btn-generate"
                onClick={handleGenerateQuiz}
                disabled={selectedTopics.length === 0 || isGeneratingQuiz || (indexedTotal === 0 && canvasIndexedDocuments.length === 0)}
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

              {indexedTotal === 0 && canvasIndexedDocuments.length === 0 && (
                <div className="message info">
                  <Info size={16} />
                  Vui lòng upload và index tài liệu PDF hoặc tải từ Canvas LMS trước khi tạo quiz.
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
            <h3>
              <FileIcon size={18} />
              Files đã upload ({uploadedTotal})
            </h3>
            <div className="files-list">
              {uploadedFiles.map((file, idx) => (
                <div key={idx} className="file-item">
                  <FileText size={16} />
                  <span className="file-name">{file.filename}</span>
                  <span className="file-size">{formatFileSize(file.size)}</span>
                </div>
              ))}
            </div>
            {uploadedPages > 1 && (
              <div className="pagination-controls">
                <button disabled={uploadedPage <= 1} onClick={() => { setUploadedPage(p => p - 1); loadUploadedFiles(uploadedPage - 1); }}>Trước</button>
                <span>Trang {uploadedPage} / {uploadedPages}</span>
                <button disabled={uploadedPage >= uploadedPages} onClick={() => { setUploadedPage(p => p + 1); loadUploadedFiles(uploadedPage + 1); }}>Sau</button>
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
                  </span>
                </div>
              )}

              {/* Document list */}
              <div className="modal-documents">
                {(topicSource === 'upload' ? indexedDocuments : canvasIndexedDocuments).length === 0 ? (
                  <div className="modal-empty-state">
                    <FileText size={32} />
                    <p>
                      {topicSource === 'upload' 
                        ? 'Chưa có tài liệu nào được index. Vui lòng upload và index tài liệu trước.'
                        : 'Chưa có tài liệu Canvas nào được index. Vui lòng vào tab Canvas LMS để tải và index tài liệu.'
                      }
                    </p>
                  </div>
                ) : (topicSource === 'upload' ? indexedDocuments : canvasIndexedDocuments).map((doc) => {
                  const isDocSelected = tempSelectedDocuments.includes(doc.filename);
                  const docTopics = tempTopicsByDocument[doc.filename] || [];
                  const selectedCount = tempSelectedTopics.filter(t => t.documentFilename === doc.filename).length;
                  
                  return (
                    <div 
                      key={doc.filename} 
                      className={`modal-doc-card ${isDocSelected ? 'expanded' : ''}`}
                    >
                      <div 
                        className="modal-doc-header"
                        onClick={() => toggleDocumentInModal(doc.filename)}
                      >
                        <div className="modal-doc-checkbox">
                          <input 
                            type="checkbox" 
                            checked={isDocSelected} 
                            onChange={() => toggleDocumentInModal(doc.filename)}
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
                          ) : (
                            <div className="modal-loading-topics">
                              <Loader2 size={16} className="spin" />
                              <span>Đang tải chủ đề...</span>
                            </div>
                          )}
                        </div>
                      )}
                    </div>
                  );
                })}
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
            <div className="quiz-modal-header">
              <h3>
                <HelpCircle size={20} />
                Quiz: {selectedTopics.length > 0 ? selectedTopics.map(t => t.topic).slice(0, 2).join(', ') + (selectedTopics.length > 2 ? '...' : '') : quizTopic}
              </h3>
              <div className="quiz-modal-header-info">
                <span className="quiz-count">{generatedQuiz.length} câu hỏi</span>
              </div>
              <button className="modal-close" onClick={() => setShowQuizModal(false)}>
                <X size={16} />
                <span>Đóng</span>
              </button>
            </div>
            
            <div className="quiz-modal-body">
              <div className="quiz-questions">
                {generatedQuiz.map((q, idx) => (
                  <div key={idx} className={`quiz-question ${editingQuestionIndex === idx ? 'editing' : ''}`}>
                    <div className="question-header">
                      <span className="question-number">Câu {q.question_number}</span>
                      {editingQuestionIndex !== idx && (
                        <button
                          className="btn-edit-question"
                          onClick={() => handleStartEdit(idx)}
                          title="Chỉnh sửa câu hỏi"
                        >
                          <Edit2 size={14} strokeWidth={2} />
                          <span>Chỉnh sửa</span>
                        </button>
                      )}
                    </div>
                    
                    {editingQuestionIndex === idx && editingQuestion ? (
                      <>
                        <textarea
                          className="edit-question-text"
                          value={editingQuestion.question}
                          onChange={(e) => handleEditQuestion('question', e.target.value)}
                          rows={2}
                        />
                        
                        <div className="question-options edit-mode">
                          {Object.entries(editingQuestion.options).map(([key, value]) => (
                            <div key={key} className="edit-option">
                              <span className="option-key">{key}</span>
                              <input
                                type="text"
                                className="edit-option-input"
                                value={value}
                                onChange={(e) => handleEditQuestion('option', [key, e.target.value])}
                              />
                              <label className="correct-label">
                                <input
                                  type="radio"
                                  name={`correct-${idx}`}
                                  checked={editingQuestion.correct_answer === key}
                                  onChange={() => handleEditQuestion('correct_answer', key)}
                                />
                                <span>Đúng</span>
                              </label>
                            </div>
                          ))}
                        </div>

                        <div className="edit-explanation">
                          <label>Giải thích:</label>
                          <textarea
                            value={editingQuestion.explanation || ''}
                            onChange={(e) => handleEditQuestion('explanation', e.target.value)}
                            rows={2}
                            placeholder="Nhập giải thích (tùy chọn)..."
                          />
                        </div>
                        
                        <div className="question-edit-actions">
                          <button
                            className="btn btn-sm btn-secondary"
                            onClick={handleCancelEdit}
                          >
                            <X size={14} />
                            Hủy
                          </button>
                          <button
                            className="btn btn-sm btn-success"
                            onClick={handleSaveQuestion}
                          >
                            <Save size={14} />
                            Lưu
                          </button>
                        </div>
                      </>
                    ) : (
                      <>
                        <div className="question-text">{q.question}</div>
                        
                        <div className="question-options">
                          {Object.entries(q.options).map(([key, value]) => (
                            <div
                              key={key}
                              className={`option-label ${key === q.correct_answer ? 'correct-answer' : ''}`}
                            >
                              <span className="option-key">{key}</span>
                              <span className="option-value">{value}</span>
                              {key === q.correct_answer && (
                                <Check size={14} className="correct-icon" style={{ color: '#10b981', marginLeft: 'auto' }} />
                              )}
                            </div>
                          ))}
                        </div>

                        {q.explanation && (
                          <div className="question-explanation">
                            <strong>Giải thích:</strong> {q.explanation}
                          </div>
                        )}
                      </>
                    )}
                  </div>
                ))}
              </div>
            </div>
            
            <div className="quiz-modal-footer">
              <button 
                className="btn btn-secondary" 
                onClick={() => setShowQuizModal(false)}
              >
                Đóng
              </button>
              <button
                className="btn btn-outline btn-download-local"
                onClick={handleDownloadQTI}
                disabled={isExporting || editingQuestionIndex !== null}
                title="Download QTI package to local machine"
              >
                <Download size={16} />
                Download
              </button>
              <button
                className="btn btn-primary btn-export"
                onClick={handleExportQTI}
                disabled={isExporting || editingQuestionIndex !== null}
              >
                {isExporting ? (
                  <><Loader2 size={16} className="spin" /> Đang chuẩn bị...</>
                ) : (
                  <><Upload size={16} /> Export to Canvas</>
                )}
              </button>
              {onDeployToCanvas && (
                <button
                  className="btn btn-primary btn-deploy-canvas"
                  onClick={() => {
                    onDeployToCanvas(generatedQuiz);
                    setShowQuizModal(false);
                  }}
                  disabled={generatedQuiz.length === 0}
                  style={{
                    background: 'linear-gradient(135deg, #3b82f6, #8b5cf6)',
                    display: 'flex',
                    alignItems: 'center',
                    gap: '6px',
                  }}
                >
                  <Rocket size={16} /> Tạo Canvas Quiz
                </button>
              )}
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

        /* Quiz Modal Styles */
        .quiz-modal {
          background: rgba(22, 33, 55, 0.97);
          backdrop-filter: blur(20px);
          border: 1px solid rgba(56, 189, 248, 0.25);
          border-radius: 16px;
          width: 100%;
          max-width: 800px;
          max-height: 90vh;
          display: flex;
          flex-direction: column;
          box-shadow: 0 20px 60px rgba(0, 0, 0, 0.6), 0 0 40px rgba(56, 189, 248, 0.08), inset 0 1px 0 rgba(255, 255, 255, 0.05);
          animation: slideUp 0.3s ease;
        }

        .quiz-modal-header {
          display: flex;
          align-items: center;
          gap: 12px;
          padding: 20px 24px;
          border-bottom: 1px solid rgba(56, 189, 248, 0.18);
          background: rgba(15, 23, 42, 0.5);
          border-radius: 16px 16px 0 0;
        }

        .quiz-modal-header h3 {
          display: flex;
          align-items: center;
          gap: 10px;
          margin: 0;
          font-size: 1.1rem;
          font-weight: 600;
          color: #e2e8f0;
          flex: 1;
          white-space: nowrap;
          overflow: hidden;
          text-overflow: ellipsis;
        }

        .quiz-modal-header h3 svg {
          color: #38bdf8;
          flex-shrink: 0;
        }

        .quiz-modal-header-info {
          display: flex;
          align-items: center;
          gap: 8px;
        }

        .quiz-count {
          padding: 4px 12px;
          background: rgba(56, 189, 248, 0.12);
          border-radius: 20px;
          font-size: 0.8rem;
          font-weight: 600;
          color: #38bdf8;
        }

        .quiz-modal-body {
          flex: 1;
          overflow-y: auto;
          padding: 20px 24px;
        }

        .quiz-modal .quiz-questions {
          display: flex;
          flex-direction: column;
          gap: 16px;
        }

        .quiz-modal .quiz-question {
          background: rgba(22, 33, 55, 0.65);
          border: 1px solid rgba(56, 189, 248, 0.16);
          border-radius: 12px;
          padding: 16px;
          transition: all 0.2s ease;
        }

        .quiz-modal .quiz-question:hover {
          border-color: rgba(56, 189, 248, 0.3);
          box-shadow: 0 2px 16px rgba(56, 189, 248, 0.1);
        }

        .quiz-modal .quiz-question.editing {
          border-color: rgba(56, 189, 248, 0.3);
          box-shadow: 0 0 0 4px rgba(56, 189, 248, 0.06);
        }

        .quiz-modal .question-header {
          display: flex;
          align-items: center;
          justify-content: space-between;
          margin-bottom: 12px;
        }

        .quiz-modal .question-number {
          font-weight: 700;
          color: #38bdf8;
          font-size: 0.9rem;
          padding: 4px 12px;
          background: rgba(56, 189, 248, 0.1);
          border-radius: 6px;
        }

        .quiz-modal .btn-edit-question {
          display: flex;
          align-items: center;
          gap: 4px;
          padding: 4px 10px;
          border: 1px solid rgba(56, 189, 248, 0.22);
          border-radius: 6px;
          background: rgba(22, 33, 55, 0.65);
          color: #94a3b8;
          font-size: 0.75rem;
          cursor: pointer;
          transition: all 0.2s ease;
        }

        .quiz-modal .btn-edit-question:hover {
          border-color: #38bdf8;
          color: #38bdf8;
          background: rgba(56, 189, 248, 0.06);
        }

        .quiz-modal .question-text {
          font-size: 0.95rem;
          line-height: 1.6;
          color: #e2e8f0;
          margin-bottom: 12px;
        }

        .quiz-modal .question-options {
          display: flex;
          flex-direction: column;
          gap: 8px;
        }

        .quiz-modal .option-label {
          display: flex;
          align-items: center;
          gap: 10px;
          padding: 10px 14px;
          border: 1px solid rgba(56, 189, 248, 0.14);
          border-radius: 8px;
          background: rgba(15, 23, 42, 0.5);
          transition: all 0.2s ease;
        }

        .quiz-modal .option-label.correct-answer {
          background: rgba(52, 211, 153, 0.08);
          border-color: rgba(52, 211, 153, 0.2);
        }

        .quiz-modal .option-key {
          font-weight: 700;
          color: #38bdf8;
          min-width: 24px;
        }

        .quiz-modal .option-value {
          flex: 1;
          color: #cbd5e1;
          font-size: 0.9rem;
        }

        .quiz-modal .question-explanation {
          margin-top: 12px;
          padding: 12px;
          background: rgba(251, 191, 36, 0.06);
          border: 1px solid rgba(251, 191, 36, 0.2);
          border-radius: 8px;
          font-size: 0.85rem;
          color: #fbbf24;
        }

        .quiz-modal .edit-question-text,
        .quiz-modal .edit-option-input,
        .quiz-modal .edit-explanation textarea {
          width: 100%;
          padding: 10px 12px;
          border: 2px solid rgba(56, 189, 248, 0.15);
          border-radius: 8px;
          font-size: 0.9rem;
          font-family: inherit;
          resize: vertical;
          transition: border-color 0.2s ease;
          color: #e2e8f0;
          background: rgba(15, 23, 42, 0.6);
        }

        .quiz-modal .edit-question-text:focus,
        .quiz-modal .edit-option-input:focus,
        .quiz-modal .edit-explanation textarea:focus {
          outline: none;
          border-color: #38bdf8;
        }

        .quiz-modal .edit-option {
          display: flex;
          align-items: center;
          gap: 10px;
          margin-bottom: 8px;
        }

        .quiz-modal .correct-label {
          display: flex;
          align-items: center;
          gap: 4px;
          font-size: 0.8rem;
          color: #94a3b8;
          cursor: pointer;
        }

        .quiz-modal .edit-explanation {
          margin-top: 12px;
        }

        .quiz-modal .edit-explanation label {
          display: block;
          margin-bottom: 6px;
          font-size: 0.85rem;
          font-weight: 500;
          color: #94a3b8;
        }

        .quiz-modal .question-edit-actions {
          display: flex;
          justify-content: flex-end;
          gap: 8px;
          margin-top: 12px;
        }

        .quiz-modal .question-edit-actions .btn {
          display: flex;
          align-items: center;
          gap: 4px;
          padding: 6px 12px;
          border-radius: 6px;
          font-size: 0.8rem;
          font-weight: 500;
          cursor: pointer;
        }

        .quiz-modal .btn-secondary {
          background: rgba(15, 23, 42, 0.6);
          border: 1px solid rgba(56, 189, 248, 0.15);
          color: #94a3b8;
        }

        .quiz-modal .btn-secondary:hover {
          background: rgba(56, 189, 248, 0.08);
          color: #e2e8f0;
        }

        .quiz-modal .btn-success {
          background: linear-gradient(135deg, #10b981 0%, #059669 100%);
          border: none;
          color: white;
        }

        .quiz-modal .btn-success:hover {
          background: linear-gradient(135deg, #059669 0%, #047857 100%);
        }

        /* Quiz Modal Footer - Fixed */
        .quiz-modal-footer {
          display: flex;
          align-items: center;
          justify-content: flex-end;
          gap: 12px;
          padding: 16px 24px;
          border-top: 1px solid rgba(56, 189, 248, 0.18);
          background: rgba(15, 23, 42, 0.5);
          border-radius: 0 0 16px 16px;
          position: sticky;
          bottom: 0;
        }

        .quiz-modal-footer .btn {
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

        .quiz-modal-footer .btn-secondary {
          background: rgba(22, 33, 55, 0.75);
          border: 1px solid rgba(56, 189, 248, 0.22);
          color: #94a3b8;
        }

        .quiz-modal-footer .btn-secondary:hover {
          background: rgba(56, 189, 248, 0.12);
          color: #e2e8f0;
        }

        .quiz-modal-footer .btn-outline {
          background: rgba(22, 33, 55, 0.75);
          border: 2px solid #38bdf8;
          color: #38bdf8;
        }

        .quiz-modal-footer .btn-outline:hover:not(:disabled) {
          background: rgba(56, 189, 248, 0.12);
        }

        .quiz-modal-footer .btn-download-local {
          display: flex;
          align-items: center;
          gap: 6px;
        }

        .quiz-modal-footer .btn-export {
          background: linear-gradient(135deg, #38bdf8 0%, #0284c7 100%);
          border: none;
          color: white;
        }

        .quiz-modal-footer .btn-export:hover:not(:disabled) {
          background: linear-gradient(135deg, #0ea5e9 0%, #0369a1 100%);
          transform: translateY(-1px);
          box-shadow: 0 4px 12px rgba(56, 189, 248, 0.4);
        }

        .quiz-modal-footer .btn-export:disabled {
          background: rgba(100, 116, 139, 0.3);
          cursor: not-allowed;
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
