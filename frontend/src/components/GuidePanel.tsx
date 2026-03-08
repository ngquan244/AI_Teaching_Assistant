/**
 * GuidePanel — Per-document User Guide
 *
 * Fetches guide documents from DB. Each panel has its own guide document
 * that can be edited independently by admins.
 *
 * Routes:
 *   /guide          → overview (grid of all guide topics)
 *   /guide/:section → detail view for a specific guide document
 */
import React, { useState, useEffect, useCallback, useMemo, useRef } from 'react';
import {
  BookOpen, Edit3, Save, X, Loader2, AlertCircle, CheckCircle2,
  MessageSquare, Upload, CheckSquare, BookText,
  GraduationCap, PenSquare, Settings, HelpCircle, Home, ChevronRight,
  ArrowLeft, ImagePlus,
} from 'lucide-react';
import { useAuth } from '../context/AuthContext';
import { useLocation, useNavigate } from 'react-router-dom';
import {
  getGuideList, getGuideByPanel, updateGuide, uploadGuideImage,
  type GuideListItem, type GuideDetailResponse,
} from '../api/guide';
import { getGuideSectionFromPath } from '../types';
import './GuidePanel.css';

/* ------------------------------------------------------------------ */
/*  Icon map — maps icon_name from DB to Lucide components            */
/* ------------------------------------------------------------------ */
const ICON_MAP: Record<string, React.ReactNode> = {
  'MessageSquare': <MessageSquare size={18} />,
  'Upload':        <Upload size={18} />,
  'CheckSquare':   <CheckSquare size={18} />,
  'BookText':      <BookText size={18} />,
  'GraduationCap': <GraduationCap size={18} />,
  'PenSquare':     <PenSquare size={18} />,
  'Settings':      <Settings size={18} />,
  'HelpCircle':    <HelpCircle size={18} />,
  'BookOpen':      <BookOpen size={18} />,
};

const ICON_MAP_LARGE: Record<string, React.ReactNode> = {
  'MessageSquare': <MessageSquare size={22} />,
  'Upload':        <Upload size={22} />,
  'CheckSquare':   <CheckSquare size={22} />,
  'BookText':      <BookText size={22} />,
  'GraduationCap': <GraduationCap size={22} />,
  'PenSquare':     <PenSquare size={22} />,
  'Settings':      <Settings size={22} />,
  'HelpCircle':    <HelpCircle size={22} />,
  'BookOpen':      <BookOpen size={22} />,
};

function getIcon(name: string | null, large = false): React.ReactNode {
  if (!name) return large ? <BookOpen size={22} /> : <BookOpen size={18} />;
  return (large ? ICON_MAP_LARGE[name] : ICON_MAP[name]) || (large ? <BookOpen size={22} /> : <BookOpen size={18} />);
}

/* ------------------------------------------------------------------ */
/*  Simple Markdown → HTML renderer (covers headings, bold, lists…)   */
/* ------------------------------------------------------------------ */
function renderMarkdown(md: string): string {
  let html = md
    .replace(/&/g, '&amp;')
    .replace(/</g, '&lt;')
    .replace(/>/g, '&gt;')
    // Images: ![alt](url)
    .replace(/!\[([^\]]*)\]\(([^)]+)\)/g, '<img src="$2" alt="$1" style="max-width:100%;border-radius:8px;margin:0.5rem 0" />')
    // Markdown links: [text](url)
    .replace(/\[([^\]]+)\]\((https?:\/\/[^)]+)\)/g, '<a href="$2" target="_blank" rel="noopener noreferrer">$1</a>')
    // Bare URLs (not already inside an href or src)
    .replace(/(?<!="|'|=)(https?:\/\/[^\s<)"']+)/g, '<a href="$1" target="_blank" rel="noopener noreferrer">$1</a>')
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
  const location = useLocation();
  const navigate = useNavigate();
  const isAdmin = user?.role === 'ADMIN';

  // State
  const [guides, setGuides] = useState<GuideListItem[]>([]);
  const [activeDetail, setActiveDetail] = useState<GuideDetailResponse | null>(null);
  const [loading, setLoading] = useState(true);
  const [detailLoading, setDetailLoading] = useState(false);
  const [editing, setEditing] = useState(false);
  const [editContent, setEditContent] = useState('');
  const [editTitle, setEditTitle] = useState('');
  const [saving, setSaving] = useState(false);
  const [error, setError] = useState('');
  const [success, setSuccess] = useState('');
  const [imageUploading, setImageUploading] = useState(false);
  const editorRef = useRef<HTMLTextAreaElement>(null);

  // Derive active section from URL
  const activeSection = useMemo(
    () => getGuideSectionFromPath(location.pathname),
    [location.pathname],
  );

  /* ---------- Fetch guide list on mount ---------- */
  const fetchGuideList = useCallback(async () => {
    try {
      setLoading(true);
      setError('');
      const res = await getGuideList();
      setGuides(res.guides || []);
    } catch (err: unknown) {
      const msg = err instanceof Error ? err.message : 'Không thể tải danh sách hướng dẫn';
      setError(msg);
    } finally {
      setLoading(false);
    }
  }, []);

  useEffect(() => { fetchGuideList(); }, [fetchGuideList]);

  /* ---------- Fetch detail when section changes ---------- */
  useEffect(() => {
    if (!activeSection) {
      setActiveDetail(null);
      return;
    }
    let cancelled = false;
    (async () => {
      try {
        setDetailLoading(true);
        setError('');
        const res = await getGuideByPanel(activeSection);
        if (!cancelled) setActiveDetail(res);
      } catch (err: unknown) {
        if (!cancelled) {
          const msg = err instanceof Error ? err.message : 'Không thể tải hướng dẫn';
          setError(msg);
          setActiveDetail(null);
        }
      } finally {
        if (!cancelled) setDetailLoading(false);
      }
    })();
    return () => { cancelled = true; };
  }, [activeSection]);

  /* ---------- Navigation helpers ---------- */
  const goToSection = (panelKey: string) => {
    navigate(`/guide/${panelKey}`);
  };

  const goToOverview = () => {
    navigate('/guide');
  };

  /* ---------- Admin editing ---------- */
  const handleEdit = () => {
    if (!activeDetail) return;
    setEditContent(activeDetail.content);
    setEditTitle(activeDetail.title);
    setEditing(true);
    setSuccess('');
  };

  const handleCancel = () => {
    setEditing(false);
    setEditContent('');
    setEditTitle('');
  };

  const handleSave = async () => {
    if (!activeDetail) return;
    try {
      setSaving(true);
      setError('');
      setSuccess('');
      const res = await updateGuide(activeDetail.panel_key, {
        content: editContent,
        title: editTitle,
      });
      setActiveDetail(res);
      setEditing(false);
      setSuccess('Đã lưu hướng dẫn thành công!');
      // Also refresh the list to pick up title changes
      fetchGuideList();
      setTimeout(() => setSuccess(''), 4000);
    } catch (err: unknown) {
      const msg = err instanceof Error ? err.message : 'Lỗi khi lưu hướng dẫn';
      setError(msg);
    } finally {
      setSaving(false);
    }
  };

  /* ---------- Image paste handler ---------- */
  const handleEditorPaste = useCallback(async (e: React.ClipboardEvent<HTMLTextAreaElement>) => {
    const items = e.clipboardData?.items;
    if (!items) return;

    for (let i = 0; i < items.length; i++) {
      const item = items[i];
      if (item.type.startsWith('image/')) {
        e.preventDefault();
        const file = item.getAsFile();
        if (!file) return;

        try {
          setImageUploading(true);
          const res = await uploadGuideImage(file);
          // Insert markdown image at cursor position
          const textarea = editorRef.current;
          if (textarea) {
            const start = textarea.selectionStart;
            const end = textarea.selectionEnd;
            const before = editContent.substring(0, start);
            const after = editContent.substring(end);
            const imageMarkdown = `![image](${res.url})`;
            setEditContent(before + imageMarkdown + after);
            // Move cursor after inserted text
            setTimeout(() => {
              textarea.selectionStart = textarea.selectionEnd = start + imageMarkdown.length;
              textarea.focus();
            }, 0);
          }
        } catch (err: unknown) {
          const msg = err instanceof Error ? err.message : 'Lỗi khi upload ảnh';
          setError(msg);
        } finally {
          setImageUploading(false);
        }
        return;
      }
    }
  }, [editContent]);

  /* ---------- Image insert via file picker ---------- */
  const handleImageInsert = useCallback(async () => {
    const input = document.createElement('input');
    input.type = 'file';
    input.accept = 'image/jpeg,image/png,image/gif,image/webp';
    input.onchange = async () => {
      const file = input.files?.[0];
      if (!file) return;
      try {
        setImageUploading(true);
        const res = await uploadGuideImage(file);
        const textarea = editorRef.current;
        if (textarea) {
          const start = textarea.selectionStart;
          const end = textarea.selectionEnd;
          const before = editContent.substring(0, start);
          const after = editContent.substring(end);
          const imageMarkdown = `![${file.name}](${res.url})`;
          setEditContent(before + imageMarkdown + after);
          setTimeout(() => {
            textarea.selectionStart = textarea.selectionEnd = start + imageMarkdown.length;
            textarea.focus();
          }, 0);
        }
      } catch (err: unknown) {
        const msg = err instanceof Error ? err.message : 'Lỗi khi upload ảnh';
        setError(msg);
      } finally {
        setImageUploading(false);
      }
    };
    input.click();
  }, [editContent]);

  // Separate visible guides: overview vs sections (excluding 'overview')
  const overviewGuide = useMemo(() => guides.find(g => g.panel_key === 'overview'), [guides]);
  const sectionGuides = useMemo(() => guides.filter(g => g.panel_key !== 'overview'), [guides]);

  /* ---------- Render ---------- */
  if (loading) {
    return (
      <div className="guide-panel">
        <div className="guide-bg-decoration">
          <div className="guide-bg-orb guide-bg-orb-1" />
          <div className="guide-bg-orb guide-bg-orb-2" />
          <div className="guide-bg-orb guide-bg-orb-3" />
        </div>
        <div className="guide-loading">
          <Loader2 className="spin" size={36} />
          <p>Đang tải hướng dẫn…</p>
        </div>
      </div>
    );
  }

  return (
    <div className="guide-panel">
      {/* BG decorations */}
      <div className="guide-bg-decoration">
        <div className="guide-bg-orb guide-bg-orb-1" />
        <div className="guide-bg-orb guide-bg-orb-2" />
        <div className="guide-bg-orb guide-bg-orb-3" />
      </div>
      <div className="guide-stars">
        {[...Array(18)].map((_, i) => (
          <div key={i} className="guide-star" style={{
            top: `${5 + Math.random() * 90}%`,
            left: `${Math.random() * 100}%`,
            animationDelay: `${Math.random() * 3}s`,
          }} />
        ))}
      </div>
      <div className="guide-glow-line guide-glow-line-1" />
      <div className="guide-glow-line guide-glow-line-2" />

      {/* Header */}
      <div className="guide-header">
        <div className="guide-title">
          <div className="guide-title-icon"><BookOpen size={24} /></div>
          <h1>Hướng dẫn sử dụng</h1>
        </div>
        {isAdmin && activeSection && !editing && (
          <button className="guide-edit-btn" onClick={handleEdit}>
            <Edit3 size={16} />
            Chỉnh sửa
          </button>
        )}
        {isAdmin && editing && (
          <div className="guide-edit-actions">
            <button
              className="guide-image-btn"
              onClick={handleImageInsert}
              disabled={imageUploading || saving}
              title="Chèn ảnh"
            >
              {imageUploading ? <Loader2 className="spin" size={16} /> : <ImagePlus size={16} />}
              Ảnh
            </button>
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
      {imageUploading && (
        <div className="guide-alert guide-alert-info">
          <Loader2 className="spin" size={18} /> Đang upload ảnh…
        </div>
      )}

      {/* Content */}
      {editing && activeDetail ? (
        /* ── Admin Editor ── */
        <div className="guide-editor-container">
          <div className="guide-editor-hint">
            Soạn nội dung bằng Markdown. Paste ảnh trực tiếp hoặc nhấn nút Ảnh để chèn. Phần xem trước hiển thị bên phải.
          </div>
          <div className="guide-editor-title-row">
            <label htmlFor="guide-title-input">Tiêu đề:</label>
            <input
              id="guide-title-input"
              className="guide-title-input"
              type="text"
              value={editTitle}
              onChange={(e) => setEditTitle(e.target.value)}
              placeholder="Tiêu đề hướng dẫn"
            />
          </div>
          <div className="guide-editor-split">
            <textarea
              ref={editorRef}
              className="guide-editor"
              value={editContent}
              onChange={(e) => setEditContent(e.target.value)}
              onPaste={handleEditorPaste}
              placeholder="# Tiêu đề&#10;&#10;Nội dung hướng dẫn...&#10;&#10;Paste ảnh trực tiếp vào đây!"
            />
            <div
              className="guide-preview guide-content"
              dangerouslySetInnerHTML={{ __html: renderMarkdown(editContent) }}
            />
          </div>
        </div>
      ) : activeSection ? (
        /* ── Section detail view ── */
        detailLoading ? (
          <div className="guide-loading">
            <Loader2 className="spin" size={36} />
            <p>Đang tải…</p>
          </div>
        ) : activeDetail ? (
          <div className="guide-layout">
            {/* Sidebar */}
            <nav className="guide-sidebar">
              <div className="guide-sidebar-label">MENU</div>
              <button
                className="guide-menu-item"
                onClick={goToOverview}
              >
                <span className="guide-menu-icon"><Home size={18} /></span>
                <span>Tổng quan</span>
                <ChevronRight size={14} className="guide-menu-chevron" />
              </button>
              <div className="guide-menu-divider" />
              {sectionGuides.map((g) => (
                <button
                  key={g.panel_key}
                  className={`guide-menu-item ${activeSection === g.panel_key ? 'active' : ''}`}
                  onClick={() => goToSection(g.panel_key)}
                >
                  <span className="guide-menu-icon">{getIcon(g.icon_name)}</span>
                  <span>{g.title}</span>
                  <ChevronRight size={14} className="guide-menu-chevron" />
                </button>
              ))}
            </nav>

            {/* Main content */}
            <div className="guide-main">
              <div className="guide-content guide-section-view" key={activeDetail.panel_key}>
                <button className="guide-back-btn" onClick={goToOverview}>
                  <ArrowLeft size={16} />
                  Quay lại tổng quan
                </button>
                <div className="guide-section-header">
                  <div className="guide-section-header-icon">
                    {getIcon(activeDetail.icon_name, true)}
                  </div>
                  <h2>{activeDetail.title}</h2>
                  {isAdmin && !activeDetail.is_published && (
                    <span className="guide-unpublished-badge">Ẩn</span>
                  )}
                </div>
                <div
                  className="guide-section-body"
                  dangerouslySetInnerHTML={{ __html: renderMarkdown(activeDetail.content) }}
                />
              </div>
            </div>
          </div>
        ) : null
      ) : guides.length > 0 ? (
        /* ── Overview / topic grid ── */
        <div className="guide-layout">
          {/* Sidebar */}
          <nav className="guide-sidebar">
            <div className="guide-sidebar-label">MENU</div>
            <button
              className="guide-menu-item active"
              onClick={goToOverview}
            >
              <span className="guide-menu-icon"><Home size={18} /></span>
              <span>Tổng quan</span>
              <ChevronRight size={14} className="guide-menu-chevron" />
            </button>
            <div className="guide-menu-divider" />
            {sectionGuides.map((g) => (
              <button
                key={g.panel_key}
                className="guide-menu-item"
                onClick={() => goToSection(g.panel_key)}
              >
                <span className="guide-menu-icon">{getIcon(g.icon_name)}</span>
                <span>{g.title}</span>
                <ChevronRight size={14} className="guide-menu-chevron" />
              </button>
            ))}
          </nav>

          {/* Main content */}
          <div className="guide-main">
            <div className="guide-content guide-intro-view" key="intro">
              {overviewGuide && (
                <div className="guide-intro-card">
                  <p className="guide-intro-text">
                    Chào mừng bạn đến với <strong>TA Grader</strong> — hệ thống trợ giảng thông minh.
                    Chọn một chủ đề bên dưới để xem hướng dẫn chi tiết.
                  </p>
                </div>
              )}
              <h2 className="guide-topics-heading">Chọn chủ đề</h2>
              <div className="guide-topic-grid">
                {sectionGuides.map((g) => (
                  <button
                    key={g.panel_key}
                    className="guide-topic-card"
                    onClick={() => goToSection(g.panel_key)}
                  >
                    <div className="guide-topic-icon">
                      {getIcon(g.icon_name, true)}
                    </div>
                    <span className="guide-topic-label">{g.title}</span>
                    <span className="guide-topic-desc">
                      {g.description || ''}
                    </span>
                    {isAdmin && !g.is_published && (
                      <span className="guide-unpublished-badge">Ẩn</span>
                    )}
                  </button>
                ))}
              </div>
            </div>
          </div>
        </div>
      ) : (
        <div className="guide-empty">
          <BookOpen size={48} strokeWidth={1.2} />
          <p>Chưa có nội dung hướng dẫn.</p>
          {isAdmin && <p>Vào từng mục để tạo nội dung hướng dẫn cho người dùng.</p>}
        </div>
      )}
    </div>
  );
};

export default GuidePanel;
