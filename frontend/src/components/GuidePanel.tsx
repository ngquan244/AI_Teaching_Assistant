/**
 * GuidePanel — User Guide page
 *
 * Menu-based navigation: users click on a topic in the sidebar to view it.
 * - All users can read the guide.
 * - Admins see an "Edit" button to switch to a Markdown editor & save.
 */
import React, { useState, useEffect, useCallback, useMemo } from 'react';
import {
  BookOpen, Edit3, Save, X, Loader2, AlertCircle, CheckCircle2,
  MessageSquare, Upload, FileQuestion, CheckSquare, BookText,
  GraduationCap, PenSquare, Settings, HelpCircle, Home, ChevronRight,
  ArrowLeft,
} from 'lucide-react';
import { useAuth } from '../context/AuthContext';
import { usePanelConfig } from '../context/PanelConfigContext';
import { getGuide, updateGuide } from '../api/guide';
import './GuidePanel.css';

/* ------------------------------------------------------------------ */
/*  Map guide section titles → panel keys                              */
/* ------------------------------------------------------------------ */
const SECTION_PANEL_MAP: Record<string, string> = {
  'chat ai': 'chat',
  'upload': 'upload',
  'tạo quiz': 'quiz',
  'chấm điểm': 'grading',
  'rag tài liệu': 'document_rag',
  'canvas lms': 'canvas',
  'tạo canvas quiz': 'canvas_quiz',
  'cài đặt': 'settings',
};

/**
 * Map FAQ question titles (lowercase substring match) → required panel keys.
 * If ANY required panel is hidden, the FAQ item is removed.
 * Questions not listed here are always shown.
 */
const FAQ_PANEL_MAP: Array<{ keywords: string[]; panels: string[] }> = [
  { keywords: ['chấm bài thi'], panels: ['upload', 'grading'] },
  { keywords: ['tài liệu đã upload', 'nội dung tài liệu'], panels: ['document_rag'] },
  { keywords: ['tính năng bị khóa'], panels: ['chat'] },
  { keywords: ['lỗi khi chấm bài'], panels: ['grading'] },
  { keywords: ['ollama', 'groq'], panels: ['settings'] },
  { keywords: ['quiz từ tài liệu', 'đẩy lên canvas'], panels: ['document_rag', 'canvas_quiz'] },
];

/* ------------------------------------------------------------------ */
/*  Icon map for menu items                                            */
/* ------------------------------------------------------------------ */
const SECTION_ICONS: Record<string, React.ReactNode> = {
  'chat ai':         <MessageSquare size={18} />,
  'upload':          <Upload size={18} />,
  'tạo quiz':        <FileQuestion size={18} />,
  'chấm điểm':      <CheckSquare size={18} />,
  'rag tài liệu':   <BookText size={18} />,
  'canvas lms':      <GraduationCap size={18} />,
  'tạo canvas quiz': <PenSquare size={18} />,
  'cài đặt':         <Settings size={18} />,
  'câu hỏi thường gặp': <HelpCircle size={18} />,
};

const SECTION_DESCRIPTIONS: Record<string, string> = {
  'chat ai':         'Giao tiếp AI bằng ngôn ngữ tự nhiên',
  'upload':          'Tải ảnh bài thi & PDF đề thi',
  'tạo quiz':        'Tạo bài kiểm tra HTML từ PDF',
  'chấm điểm':      'Chấm bài trắc nghiệm tự động',
  'rag tài liệu':   'Hỏi đáp thông minh từ tài liệu',
  'canvas lms':      'Tích hợp hệ thống Canvas',
  'tạo canvas quiz': 'Tạo & đẩy quiz lên Canvas',
  'cài đặt':         'Cấu hình model AI & Canvas',
  'câu hỏi thường gặp': 'Giải đáp thắc mắc phổ biến',
};

/* ------------------------------------------------------------------ */
/*  Types                                                              */
/* ------------------------------------------------------------------ */
interface GuideSection {
  id: string;          // kebab-case slug
  title: string;       // original heading text
  titleLower: string;  // lowercased for lookup
  body: string;        // markdown body (without ## heading)
}

/* ------------------------------------------------------------------ */
/*  Parse markdown into sections                                       */
/* ------------------------------------------------------------------ */
function parseSections(md: string): { intro: string; sections: GuideSection[] } {
  const parts = md.split(/^(?=## )/m);
  let intro = '';
  const sections: GuideSection[] = [];

  for (const part of parts) {
    if (!part.startsWith('## ')) {
      intro = part.trim();
      continue;
    }
    const headingMatch = part.match(/^## (.+)$/m);
    if (!headingMatch) continue;

    const title = headingMatch[1].trim();
    const body = part.replace(/^## .+\n?/, '').trim();
    const id = title
      .toLowerCase()
      .replace(/\s+/g, '-')
      .replace(/[^a-z0-9\u00C0-\u024F\u1E00-\u1EFF-]/g, '');

    sections.push({ id, title, titleLower: title.toLowerCase(), body });
  }

  return { intro, sections };
}

/* ------------------------------------------------------------------ */
/*  Filter logic (same as before, but works on parsed sections)        */
/* ------------------------------------------------------------------ */
function filterSections(
  sections: GuideSection[],
  isPanelVisible: (key: string) => boolean,
): GuideSection[] {
  return sections
    .filter((s) => {
      const panelKey = SECTION_PANEL_MAP[s.titleLower];
      if (!panelKey) return true;
      return isPanelVisible(panelKey);
    })
    .map((s) => {
      // Filter FAQ items inside FAQ section
      if (s.titleLower === 'câu hỏi thường gặp') {
        const faqParts = s.body.split(/^(?=### )/m);
        const filtered = faqParts.filter((faq) => {
          if (!faq.startsWith('### ')) return true;
          const faqTitle = (faq.match(/^### (.+)$/m)?.[1] || '').toLowerCase();
          for (const rule of FAQ_PANEL_MAP) {
            if (rule.keywords.some((kw) => faqTitle.includes(kw))) {
              return rule.panels.every((p) => isPanelVisible(p));
            }
          }
          return true;
        });
        return { ...s, body: filtered.join('') };
      }
      return s;
    });
}

function filterIntro(intro: string, isPanelVisible: (key: string) => boolean): string {
  let result = intro;
  const featurePanelMap: Record<string, string> = {
    'Chat AI': 'chat',
    'Upload bài thi': 'upload',
    'Tạo Quiz': 'quiz',
    'Chấm điểm tự động': 'grading',
    'RAG Tài Liệu': 'document_rag',
    'Canvas LMS': 'canvas',
    'Tạo Canvas Quiz': 'canvas_quiz',
  };
  for (const [featureName, panelKey] of Object.entries(featurePanelMap)) {
    if (!isPanelVisible(panelKey)) {
      result = result.replace(
        new RegExp(`,?\\s*\\*\\*${featureName.replace(/[.*+?^${}()|[\]\\]/g, '\\$&')}\\*\\*,?`, 'g'),
        (match) => (match.startsWith(',') && match.endsWith(',') ? ',' : ''),
      );
    }
  }
  result = result.replace(/,\s*,/g, ',');
  result = result.replace(/:\s*,\s*/g, ': ');
  result = result.replace(/,\s*\./g, '.');
  return result;
}

/* ------------------------------------------------------------------ */
/*  Simple Markdown → HTML renderer (covers headings, bold, lists…)   */
/* ------------------------------------------------------------------ */
function renderMarkdown(md: string): string {
  let html = md
    .replace(/&/g, '&amp;')
    .replace(/</g, '&lt;')
    .replace(/>/g, '&gt;')
    .replace(/^### (.+)$/gm, '<h3>$1</h3>')
    .replace(/^## (.+)$/gm, '<h2>$1</h2>')
    .replace(/^# (.+)$/gm, '<h1>$1</h1>')
    .replace(/\*\*(.+?)\*\*/g, '<strong>$1</strong>')
    .replace(/\*(.+?)\*/g, '<em>$1</em>')
    .replace(/`([^`]+)`/g, '<code>$1</code>')
    .replace(/^---$/gm, '<hr />')
    .replace(/\n{2,}/g, '</p><p>')
    .replace(/^- (.+)$/gm, '<li>$1</li>')
    .replace(/^\d+\.\s+(.+)$/gm, '<li>$1</li>');
  html = html.replace(/((?:<li>.*<\/li>\s*)+)/g, '<ul>$1</ul>');
  html = html.replace(/\n/g, '<br />');
  return `<p>${html}</p>`;
}

/* ================================================================== */
/*  Component                                                          */
/* ================================================================== */
const GuidePanel: React.FC = () => {
  const { user } = useAuth();
  const { isPanelVisible } = usePanelConfig();
  const isAdmin = user?.role === 'ADMIN';

  const [content, setContent] = useState('');
  const [editContent, setEditContent] = useState('');
  const [editing, setEditing] = useState(false);
  const [loading, setLoading] = useState(true);
  const [saving, setSaving] = useState(false);
  const [error, setError] = useState('');
  const [success, setSuccess] = useState('');
  const [activeSection, setActiveSection] = useState<string | null>(null); // null = intro

  /* ---------- Parsed & filtered data ---------- */
  const parsed = useMemo(() => parseSections(content), [content]);

  const visibleSections = useMemo(() => {
    if (isAdmin) return parsed.sections;
    return filterSections(parsed.sections, isPanelVisible);
  }, [parsed.sections, isAdmin, isPanelVisible]);

  const visibleIntro = useMemo(() => {
    if (isAdmin) return parsed.intro;
    return filterIntro(parsed.intro, isPanelVisible);
  }, [parsed.intro, isAdmin, isPanelVisible]);

  // Reset active section if it got filtered out
  useEffect(() => {
    if (activeSection && !visibleSections.find((s) => s.id === activeSection)) {
      setActiveSection(null);
    }
  }, [activeSection, visibleSections]);

  /* ---------- Active section content ---------- */
  const currentSection = useMemo(
    () => visibleSections.find((s) => s.id === activeSection) ?? null,
    [activeSection, visibleSections],
  );

  /* ---------- Fetch guide on mount ---------- */
  const fetchGuide = useCallback(async () => {
    try {
      setLoading(true);
      setError('');
      const res = await getGuide();
      setContent(res.content || '');
    } catch (err: unknown) {
      const msg = err instanceof Error ? err.message : 'Không thể tải hướng dẫn';
      setError(msg);
    } finally {
      setLoading(false);
    }
  }, []);

  useEffect(() => { fetchGuide(); }, [fetchGuide]);

  /* ---------- Admin editing ---------- */
  const handleEdit = () => { setEditContent(content); setEditing(true); setSuccess(''); };
  const handleCancel = () => { setEditing(false); setEditContent(''); };

  const handleSave = async () => {
    try {
      setSaving(true); setError(''); setSuccess('');
      const res = await updateGuide(editContent);
      setContent(res.content);
      setEditing(false);
      setSuccess('Đã lưu hướng dẫn thành công!');
      setTimeout(() => setSuccess(''), 4000);
    } catch (err: unknown) {
      const msg = err instanceof Error ? err.message : 'Lỗi khi lưu hướng dẫn';
      setError(msg);
    } finally {
      setSaving(false);
    }
  };

  /* ---------- Render ---------- */
  if (loading) {
    return (
      <div className="guide-panel">
        <div className="guide-loading">
          <Loader2 className="spin" size={36} />
          <p>Đang tải hướng dẫn…</p>
        </div>
      </div>
    );
  }

  return (
    <div className="guide-panel">
      {/* Header */}
      <div className="guide-header">
        <div className="guide-title">
          <BookOpen size={28} />
          <h1>Hướng dẫn sử dụng</h1>
        </div>
        {isAdmin && !editing && (
          <button className="guide-edit-btn" onClick={handleEdit}>
            <Edit3 size={16} />
            Chỉnh sửa
          </button>
        )}
        {isAdmin && editing && (
          <div className="guide-edit-actions">
            <button className="guide-save-btn" onClick={handleSave} disabled={saving}>
              {saving ? <Loader2 className="spin" size={16} /> : <Save size={16} />}
              {saving ? 'Đang lưu…' : 'Lưu'}
            </button>
            <button className="guide-cancel-btn" onClick={handleCancel} disabled={saving}>
              <X size={16} />
              Hủy
            </button>
          </div>
        )}
      </div>

      {/* Alerts */}
      {error && (
        <div className="guide-alert guide-alert-error">
          <AlertCircle size={18} /> {error}
        </div>
      )}
      {success && (
        <div className="guide-alert guide-alert-success">
          <CheckCircle2 size={18} /> {success}
        </div>
      )}

      {/* Content */}
      {editing ? (
        <div className="guide-editor-container">
          <div className="guide-editor-hint">
            Soạn nội dung bằng Markdown. Phần xem trước hiển thị bên phải.
          </div>
          <div className="guide-editor-split">
            <textarea
              className="guide-editor"
              value={editContent}
              onChange={(e) => setEditContent(e.target.value)}
              placeholder="# Tiêu đề&#10;&#10;Nội dung hướng dẫn..."
            />
            <div
              className="guide-preview guide-content"
              dangerouslySetInnerHTML={{ __html: renderMarkdown(editContent) }}
            />
          </div>
        </div>
      ) : content ? (
        <div className="guide-layout">
          {/* ── Sidebar menu ── */}
          <nav className="guide-sidebar">
            <div className="guide-sidebar-label">MENU</div>
            <button
              className={`guide-menu-item ${activeSection === null ? 'active' : ''}`}
              onClick={() => setActiveSection(null)}
            >
              <span className="guide-menu-icon"><Home size={18} /></span>
              <span>Tổng quan</span>
              <ChevronRight size={14} className="guide-menu-chevron" />
            </button>

            <div className="guide-menu-divider" />

            {visibleSections.map((s) => (
              <button
                key={s.id}
                className={`guide-menu-item ${activeSection === s.id ? 'active' : ''}`}
                onClick={() => setActiveSection(s.id)}
              >
                <span className="guide-menu-icon">{SECTION_ICONS[s.titleLower] || <BookOpen size={18} />}</span>
                <span>{s.title}</span>
                <ChevronRight size={14} className="guide-menu-chevron" />
              </button>
            ))}
          </nav>

          {/* ── Main content area ── */}
          <div className="guide-main">
            {activeSection === null ? (
              /* Intro / overview */
              <div className="guide-content guide-intro-view" key="intro">
                {visibleIntro && (
                  <div className="guide-intro-card" dangerouslySetInnerHTML={{ __html: renderMarkdown(visibleIntro) }} />
                )}
                <h2 className="guide-topics-heading">Chọn chủ đề</h2>
                <div className="guide-topic-grid">
                  {visibleSections.map((s) => (
                    <button
                      key={s.id}
                      className="guide-topic-card"
                      onClick={() => setActiveSection(s.id)}
                    >
                      <div className="guide-topic-icon">
                        {SECTION_ICONS[s.titleLower] || <BookOpen size={22} />}
                      </div>
                      <span className="guide-topic-label">{s.title}</span>
                      <span className="guide-topic-desc">
                        {SECTION_DESCRIPTIONS[s.titleLower] || ''}
                      </span>
                    </button>
                  ))}
                </div>
              </div>
            ) : currentSection ? (
              /* Section detail */
              <div className="guide-content guide-section-view" key={currentSection.id}>
                <button className="guide-back-btn" onClick={() => setActiveSection(null)}>
                  <ArrowLeft size={16} />
                  Quay lại tổng quan
                </button>
                <div className="guide-section-header">
                  <div className="guide-section-header-icon">
                    {SECTION_ICONS[currentSection.titleLower] || <BookOpen size={24} />}
                  </div>
                  <h2>{currentSection.title}</h2>
                </div>
                <div className="guide-section-body" dangerouslySetInnerHTML={{ __html: renderMarkdown(currentSection.body) }} />
              </div>
            ) : null}
          </div>
        </div>
      ) : (
        <div className="guide-empty">
          <BookOpen size={48} strokeWidth={1.2} />
          <p>Chưa có nội dung hướng dẫn.</p>
          {isAdmin && <p>Nhấn <strong>Chỉnh sửa</strong> để bắt đầu viết hướng dẫn cho người dùng.</p>}
        </div>
      )}
    </div>
  );
};

export default GuidePanel;
