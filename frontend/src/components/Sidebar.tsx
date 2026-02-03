import React from 'react';
import { MessageSquare, FileUp, BookOpen, BarChart3, Settings, GraduationCap, FileText, FolderOpen } from 'lucide-react';
import { TABS, type TabType } from '../types';

interface SidebarProps {
  activeTab: TabType;
  onTabChange: (tab: TabType) => void;
}

interface TabItem {
  id: TabType;
  label: string;
  icon: typeof MessageSquare;
}

const SIDEBAR_TABS: TabItem[] = [
  { id: TABS.CHAT, label: 'Chat AI', icon: MessageSquare },
  { id: TABS.UPLOAD, label: 'Upload', icon: FileUp },
  { id: TABS.QUIZ, label: 'Tạo Quiz', icon: BookOpen },
  { id: TABS.GRADING, label: 'Chấm điểm', icon: BarChart3 },
  { id: TABS.DOCUMENT_RAG, label: 'RAG Tài liệu', icon: FileText },
  { id: TABS.CANVAS, label: 'Canvas LMS', icon: FolderOpen },
  { id: TABS.SETTINGS, label: 'Cài đặt', icon: Settings },
];

const Sidebar: React.FC<SidebarProps> = ({ activeTab, onTabChange }) => {
  return (
    <div className="sidebar">
      <div className="sidebar-header">
        <GraduationCap size={32} />
        <h1>TA Grader</h1>
      </div>

      <nav className="sidebar-nav">
        {SIDEBAR_TABS.map((tab) => {
          const Icon = tab.icon;
          return (
            <button
              key={tab.id}
              className={`nav-item ${activeTab === tab.id ? 'active' : ''}`}
              onClick={() => onTabChange(tab.id)}
            >
              <Icon size={20} />
              <span>{tab.label}</span>
            </button>
          );
        })}
      </nav>

      <div className="sidebar-footer">
        <p>Teaching Assistant</p>
        <p className="version">v1.0.0</p>
      </div>
    </div>
  );
};

export default Sidebar;
