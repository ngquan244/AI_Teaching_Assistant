import React from 'react';
import { useNavigate } from 'react-router-dom';
import { MessageSquare, FileUp, BarChart3, Settings, GraduationCap, FileText, FolderOpen, PenSquare, ShieldCheck, HelpCircle, PlayCircle, PieChart } from 'lucide-react';
import { TABS, TAB_PATHS, type TabType } from '../types';
import { useAuth } from '../context/AuthContext';
import { usePanelConfig } from '../context/PanelConfigContext';
import UserMenu from './UserMenu';

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
  { id: TABS.GRADING, label: 'Chấm điểm', icon: BarChart3 },
  { id: TABS.DOCUMENT_RAG, label: 'Tài Liệu', icon: FileText },
  { id: TABS.CANVAS, label: 'Canvas LMS', icon: FolderOpen },
  { id: TABS.CANVAS_QUIZ, label: 'Tạo Canvas Quiz', icon: PenSquare },
  { id: TABS.CANVAS_SIMULATION, label: 'Giả lập Quiz', icon: PlayCircle },
  { id: TABS.CANVAS_RESULTS, label: 'Kết quả Canvas', icon: PieChart },
  { id: TABS.GUIDE, label: 'Hướng dẫn', icon: HelpCircle },
  { id: TABS.SETTINGS, label: 'Cài đặt', icon: Settings },
];

const Sidebar: React.FC<SidebarProps> = ({ activeTab, onTabChange }) => {
  const navigate = useNavigate();
  const { user } = useAuth();
  const { isPanelVisible } = usePanelConfig();

  const handleTabClick = (tab: TabType) => {
    navigate('/' + TAB_PATHS[tab]);
    onTabChange(tab);
  };

  // Filter out disabled panels (admins always see all panels)
  const visibleTabs = user?.role === 'ADMIN'
    ? SIDEBAR_TABS
    : SIDEBAR_TABS.filter((tab) => isPanelVisible(tab.id));

  return (
    <div className="sidebar">
      <div className="sidebar-header">
        <GraduationCap size={32} />
        <h1>TA Grader</h1>
      </div>

      <nav className="sidebar-nav">
        {visibleTabs.map((tab) => {
          const Icon = tab.icon;
          return (
            <button
              key={tab.id}
              className={`nav-item ${activeTab === tab.id ? 'active' : ''}`}
              onClick={() => handleTabClick(tab.id)}
            >
              <Icon size={20} />
              <span>{tab.label}</span>
            </button>
          );
        })}

        {/* Admin Panel link — only visible to ADMIN users */}
        {user?.role === 'ADMIN' && (
          <button
            className="nav-item admin-panel-link"
            onClick={() => navigate('/admin')}
          >
            <ShieldCheck size={20} />
            <span>Admin Panel</span>
          </button>
        )}
      </nav>

      {/* User menu with logout */}
      <UserMenu />
    </div>
  );
};

export default Sidebar;
