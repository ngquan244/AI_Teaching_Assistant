import { useState, useCallback, useEffect } from 'react';
import { useLocation, useNavigate } from 'react-router-dom';
import { AppProvider, useApp } from './context/AppContext';
import { usePanelConfig, getFirstVisibleTab } from './context/PanelConfigContext';
import { useAuth } from './context/AuthContext';
import { Sidebar, ChatPanel, UploadPanel, QuizPanel, GradingPanel, SettingsPanel, DocumentRAGPanel, CanvasFilesPanel, QuizBuilderPanel } from './components';
import { Loader2 } from 'lucide-react';
import { TABS, TAB_PATHS, pathToTab } from './types';
import type { QuizQuestion } from './api/documentRag';
import type { QuizBuilderQuestion } from './types/canvas';
import './App.css';

const ALL_TAB_KEYS = Object.values(TABS);

const AppContent: React.FC = () => {
  const { loading } = useApp();
  const location = useLocation();
  const navigate = useNavigate();
  const { isPanelVisible, loaded: panelConfigLoaded } = usePanelConfig();
  const { user } = useAuth();

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
      navigate('/' + TAB_PATHS[redirect], { replace: true });
    }
  }, [activeTab, isPanelVisible, panelConfigLoaded, isAdmin, navigate]);

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
        {checkVisible(TABS.QUIZ) && (
          <div className="panel-padded" style={{ display: activeTab === TABS.QUIZ ? 'block' : 'none', height: '100%' }}>
            <QuizPanel />
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
