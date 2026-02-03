import { useState } from 'react';
import { AppProvider, useApp } from './context/AppContext';
import { Sidebar, ChatPanel, UploadPanel, QuizPanel, GradingPanel, SettingsPanel, DocumentRAGPanel, CanvasFilesPanel } from './components';
import { Loader2 } from 'lucide-react';
import { TABS, type TabType } from './types';
import './App.css';

const AppContent: React.FC = () => {
  const { loading } = useApp();
  const [activeTab, setActiveTab] = useState<TabType>(TABS.CHAT);

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
  return (
    <div className="app">
      <Sidebar activeTab={activeTab} onTabChange={setActiveTab} />
      <main className="main-content">
        <div style={{ display: activeTab === TABS.CHAT ? 'block' : 'none', height: '100%' }}>
          <ChatPanel />
        </div>
        <div style={{ display: activeTab === TABS.UPLOAD ? 'block' : 'none', height: '100%' }}>
          <UploadPanel />
        </div>
        <div style={{ display: activeTab === TABS.QUIZ ? 'block' : 'none', height: '100%' }}>
          <QuizPanel />
        </div>
        <div style={{ display: activeTab === TABS.GRADING ? 'block' : 'none', height: '100%' }}>
          <GradingPanel />
        </div>
        <div style={{ display: activeTab === TABS.DOCUMENT_RAG ? 'block' : 'none', height: '100%' }}>
          <DocumentRAGPanel />
        </div>
        <div style={{ display: activeTab === TABS.CANVAS ? 'block' : 'none', height: '100%' }}>
          <CanvasFilesPanel />
        </div>
        <div style={{ display: activeTab === TABS.SETTINGS ? 'block' : 'none', height: '100%' }}>
          <SettingsPanel />
        </div>
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
