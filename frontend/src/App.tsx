import { useState, useCallback, useEffect, useRef } from 'react';
import { useLocation, useNavigate } from 'react-router-dom';
import { AppProvider, useApp } from './context/AppContext';
import { usePanelConfig, getFirstVisibleTab } from './context/PanelConfigContext';
import { useModelConfig } from './context/ModelConfigContext';
import { useAuth } from './context/AuthContext';
import { useToast } from './context/ToastContext';
import { Sidebar, ChatPanel, UploadPanel, GradingPanel, SettingsPanel, DocumentRAGPanel, CanvasFilesPanel, QuizBuilderPanel, GuidePanel, CanvasSimulationPanel, CanvasResultsPanel } from './components';
import { Loader2 } from 'lucide-react';
import { TABS, TAB_PATHS, pathToTab } from './types';
import type { QuizQuestion } from './api/documentRag';
import type { QuizBuilderQuestion } from './types/canvas';
import './App.css';

const ALL_TAB_KEYS = Object.values(TABS);

/** Human-friendly panel names for toast messages */
const TAB_LABELS: Record<string, string> = {
  chat: 'Chat AI',
  upload: 'Upload',
  grading: 'Chấm bài',
  document_rag: 'Tài liệu RAG',
  canvas: 'Canvas',
  canvas_quiz: 'Quiz Builder',
  canvas_simulation: 'Giả lập Quiz',
  canvas_results: 'Kết quả Canvas',
  guide: 'Hướng dẫn',
  settings: 'Cài đặt',
};

const AppContent: React.FC = () => {
  const { loading, config, switchProvider } = useApp();
  const location = useLocation();
  const navigate = useNavigate();
  const { isPanelVisible, loaded: panelConfigLoaded } = usePanelConfig();
  const { isProviderEnabled, enabledProviders, loaded: modelConfigLoaded } = useModelConfig();
  const { user } = useAuth();
  const { showToast } = useToast();

  // Admins always see all panels
  const isAdmin = user?.role === 'ADMIN';
  const checkVisible = (key: string) => isAdmin || isPanelVisible(key);

  // Derive active tab from the current URL path
  const activeTab = pathToTab(location.pathname);

  /** Navigate to a tab by updating the URL */
  const setActiveTab = useCallback(
    (tab: typeof activeTab) => {
      navigate('/' + TAB_PATHS[tab], { replace: false });
    },
    [navigate],
  );

  // Redirect to first visible tab if current tab is disabled
  useEffect(() => {
    if (!panelConfigLoaded || isAdmin) return;
    const redirect = getFirstVisibleTab(activeTab, isPanelVisible, ALL_TAB_KEYS);
    if (redirect) {
      const label = TAB_LABELS[activeTab] || activeTab;
      showToast(`Panel "${label}" đã bị quản trị viên tắt. Đang chuyển sang tab khác...`, 'warning', 5000);
      navigate('/' + TAB_PATHS[redirect], { replace: true });
    }
  }, [activeTab, isPanelVisible, panelConfigLoaded, isAdmin, navigate, showToast]);

  // Auto-switch provider if current provider was disabled by admin
  const prevProviderRef = useRef(config?.llm_provider);
  useEffect(() => {
    if (!modelConfigLoaded || isAdmin || !config) return;

    const current = config.llm_provider || 'groq';
    // Only act if the current provider just became disabled
    if (!isProviderEnabled(current) && enabledProviders.length > 0) {
      const newProvider = enabledProviders[0];
      // Prevent duplicate switches
      if (prevProviderRef.current !== newProvider) {
        prevProviderRef.current = newProvider;
        const provLabel = current === 'groq' ? 'Groq' : 'Ollama';
        showToast(`Provider "${provLabel}" đã bị tắt bởi quản trị viên. Tự động chuyển sang ${enabledProviders[0]}.`, 'warning', 5000);
        switchProvider(enabledProviders[0] as 'ollama' | 'groq');
      }
    } else {
      prevProviderRef.current = current;
    }
  }, [modelConfigLoaded, isAdmin, config, isProviderEnabled, enabledProviders, switchProvider, showToast]);

  // Shared state: questions to inject into QuizBuilder from other panels
  const [quizBuilderQuestions, setQuizBuilderQuestions] = useState<QuizBuilderQuestion[]>([]);

  /** Called by DocumentRAGPanel / CanvasImportModal to send questions to QuizBuilder */
  const handleDeployToQuizBuilder = useCallback((questions: QuizQuestion[]) => {
    // Backend QuizQuestion has correct_answer (string), QuizBuilderQuestion needs correct (Record)
    const mapped: QuizBuilderQuestion[] = questions.map((q) => {
      const correctKey = q.correct_answer ?? 'A';
      const correctText = q.options?.[correctKey as keyof typeof q.options] ?? correctKey;
      return {
        question: q.question,
        options: q.options as unknown as Record<string, string>,
        correct: { [correctKey]: correctText },
      };
    });
    setQuizBuilderQuestions(mapped);
    navigate('/' + TAB_PATHS[TABS.CANVAS_QUIZ], { replace: false });
  }, [navigate]);

  if (loading) {
    return (
      <div className="loading-screen">
        <Loader2 className="spin" size={48} />
        <p>Đang tải...</p>
      </div>
    );
  }

  // Render all panels but only show the active one
  // This preserves state when switching tabs
  // Disabled panels are not rendered at all
  return (
    <div className="app">
      <Sidebar activeTab={activeTab} onTabChange={setActiveTab} />
      <main className="main-content">
        {checkVisible(TABS.CHAT) && (
          <div style={{ display: activeTab === TABS.CHAT ? 'block' : 'none', height: '100%' }}>
            <ChatPanel />
          </div>
        )}
        {checkVisible(TABS.UPLOAD) && (
          <div className="panel-padded" style={{ display: activeTab === TABS.UPLOAD ? 'block' : 'none', height: '100%' }}>
            <UploadPanel />
          </div>
        )}
        {checkVisible(TABS.GRADING) && (
          <div className="panel-padded" style={{ display: activeTab === TABS.GRADING ? 'block' : 'none', height: '100%' }}>
            <GradingPanel />
          </div>
        )}
        {checkVisible(TABS.DOCUMENT_RAG) && (
          <div style={{ display: activeTab === TABS.DOCUMENT_RAG ? 'block' : 'none', height: '100%' }}>
            <DocumentRAGPanel onDeployToCanvas={handleDeployToQuizBuilder} />
          </div>
        )}
        {checkVisible(TABS.CANVAS) && (
          <div style={{ display: activeTab === TABS.CANVAS ? 'block' : 'none', height: '100%' }}>
            <CanvasFilesPanel />
          </div>
        )}
        {checkVisible(TABS.CANVAS_QUIZ) && (
          <div style={{ display: activeTab === TABS.CANVAS_QUIZ ? 'block' : 'none', height: '100%' }}>
            <QuizBuilderPanel
              questions={quizBuilderQuestions}
              onQuestionsClear={() => setQuizBuilderQuestions([])}
            />
          </div>
        )}
        {checkVisible(TABS.CANVAS_SIMULATION) && (
          <div style={{ display: activeTab === TABS.CANVAS_SIMULATION ? 'block' : 'none', height: '100%' }}>
            <CanvasSimulationPanel />
          </div>
        )}
        {checkVisible(TABS.CANVAS_RESULTS) && (
          <div style={{ display: activeTab === TABS.CANVAS_RESULTS ? 'block' : 'none', height: '100%' }}>
            <CanvasResultsPanel />
          </div>
        )}
        {checkVisible(TABS.GUIDE) && (
          <div style={{ display: activeTab === TABS.GUIDE ? 'block' : 'none', height: '100%' }}>
            <GuidePanel />
          </div>
        )}
        {checkVisible(TABS.SETTINGS) && (
          <div className="panel-padded" style={{ display: activeTab === TABS.SETTINGS ? 'block' : 'none', height: '100%' }}>
            <SettingsPanel />
          </div>
        )}
      </main>
    </div>
  );
};

function App() {
  return (
    <AppProvider>
      <AppContent />
    </AppProvider>
  );
}

export default App;
