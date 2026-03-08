import React, { useState, useRef, useEffect, useMemo, useCallback } from 'react';
import { useNavigate } from 'react-router-dom';
import { chatApi } from '../api/chat';
import { useApp } from '../context/AppContext';
import { useModelConfig } from '../context/ModelConfigContext';
import { getToolsConfig, type ToolsConfigPublic } from '../api/admin';
import { Send, Loader2, Trash2, Bot, User, Sparkles, GraduationCap, FileText, Wrench, ArrowDown, MessageSquare, ChevronDown, Zap, Monitor, RefreshCw, HelpCircle } from 'lucide-react';
import PanelHelpButton from './PanelHelpButton';
import type { ChatMessage } from '../types';

/**
 * Render chat message text with clickable links.
 * Supports markdown links [text](url) and plain URLs.
 */
function renderMessageContent(text: string, onNavigate: (path: string) => void): React.ReactNode {
  // Match markdown links [label](url) or plain https?:// URLs
  const linkRegex = /\[([^\]]+)\]\((\/[^)]+|https?:\/\/[^)]+)\)|(\/guide\b)|(https?:\/\/[^\s)]+)/g;
  const parts: React.ReactNode[] = [];
  let lastIndex = 0;
  let match: RegExpExecArray | null;

  while ((match = linkRegex.exec(text)) !== null) {
    // Push text before the match
    if (match.index > lastIndex) {
      parts.push(text.slice(lastIndex, match.index));
    }

    if (match[1] && match[2]) {
      // Markdown link: [label](url)
      const label = match[1];
      const url = match[2];
      if (url.startsWith('/')) {
        // Internal link — use SPA navigation
        parts.push(
          <a
            key={match.index}
            href={url}
            className="chat-link"
            onClick={(e) => { e.preventDefault(); onNavigate(url); }}
          >
            {label}
          </a>
        );
      } else {
        // External link
        parts.push(
          <a key={match.index} href={url} className="chat-link" target="_blank" rel="noopener noreferrer">
            {label}
          </a>
        );
      }
    } else {
      // Plain URL or bare /guide
      const url = match[3] || match[4];
      const label = url.startsWith('/') ? 'Hướng dẫn' : url;
      if (url.startsWith('/')) {
        parts.push(
          <a
            key={match.index}
            href={url}
            className="chat-link"
            onClick={(e) => { e.preventDefault(); onNavigate(url); }}
          >
            {label}
          </a>
        );
      } else {
        parts.push(
          <a key={match.index} href={url} className="chat-link" target="_blank" rel="noopener noreferrer">
            {label}
          </a>
        );
      }
    }

    lastIndex = match.index + match[0].length;
  }

  // Push remaining text
  if (lastIndex < text.length) {
    parts.push(text.slice(lastIndex));
  }

  return parts.length > 0 ? parts : text;
}

/* ---------- tiny helper: random stars ---------- */
const generateStars = (count: number) =>
  Array.from({ length: count }, (_, i) => ({
    id: i,
    top: `${Math.random() * 100}%`,
    left: `${Math.random() * 100}%`,
    duration: `${3 + Math.random() * 4}s`,
    delay: `${Math.random() * 5}s`,
    size: `${1.5 + Math.random() * 1.5}px`,
  }));

const ChatPanel: React.FC = () => {
  const navigate = useNavigate();
  const { model, setModel, maxIterations, chatMessages, setChatMessages, chatToolsUsed, setChatToolsUsed, clearChat, config, switchProvider, switchingProvider } = useApp();
  const { showProviderSwitch, showModelSelector, isProviderEnabled } = useModelConfig();
  const [showModelDropdown, setShowModelDropdown] = useState(false);
  const modelDropdownRef = useRef<HTMLDivElement>(null);
  const [input, setInput] = useState('');
  const [loading, setLoading] = useState(false);
  const [showScrollBtn, setShowScrollBtn] = useState(false);
  const messagesEndRef = useRef<HTMLDivElement>(null);
  const messagesContainerRef = useRef<HTMLDivElement>(null);

  const stars = useMemo(() => generateStars(28), []);

  // ---------- Tool config for dynamic suggestions ----------
  const [toolConfig, setToolConfig] = useState<ToolsConfigPublic | null>(null);
  useEffect(() => {
    getToolsConfig().then(setToolConfig).catch(() => {});
  }, []);

  const scrollToBottom = () => {
    const container = messagesContainerRef.current;
    if (container) {
      container.scrollTop = container.scrollHeight;
    }
  };

  useEffect(() => {
    // Use requestAnimationFrame to ensure DOM has updated before scrolling
    requestAnimationFrame(() => scrollToBottom());
  }, [chatMessages]);

  useEffect(() => {
    const container = messagesContainerRef.current;
    if (!container) return;
    const handleScroll = () => {
      const { scrollTop, scrollHeight, clientHeight } = container;
      setShowScrollBtn(scrollHeight - scrollTop - clientHeight > 100);
    };
    container.addEventListener('scroll', handleScroll);
    return () => container.removeEventListener('scroll', handleScroll);
  }, []);

  // Close model dropdown on outside click
  useEffect(() => {
    const handleClickOutside = (e: MouseEvent) => {
      if (modelDropdownRef.current && !modelDropdownRef.current.contains(e.target as Node)) {
        setShowModelDropdown(false);
      }
    };
    if (showModelDropdown) {
      document.addEventListener('mousedown', handleClickOutside);
    }
    return () => document.removeEventListener('mousedown', handleClickOutside);
  }, [showModelDropdown]);

  const handleSend = async () => {
    if (!input.trim() || loading) return;

    const userMessage: ChatMessage = { role: 'user', content: input };
    setChatMessages((prev) => [...prev, userMessage]);
    setInput('');
    setLoading(true);
    setChatToolsUsed([]);

    try {
      const response = await chatApi.sendMessage({
        message: input,
        history: chatMessages,
        model,
        max_iterations: maxIterations,
      });

      const assistantMessage: ChatMessage = {
        role: 'assistant',
        content: response.response,
      };
      setChatMessages((prev) => [...prev, assistantMessage]);
      setChatToolsUsed(response.tools_used || []);
    } catch (error) {
      console.error('Chat error:', error);
      const errorMessage: ChatMessage = {
        role: 'assistant',
        content: 'Xin lỗi, đã xảy ra lỗi khi xử lý tin nhắn của bạn.',
      };
      setChatMessages((prev) => [...prev, errorMessage]);
    } finally {
      setLoading(false);
    }
  };

  const handleKeyPress = (e: React.KeyboardEvent) => {
    if (e.key === 'Enter' && !e.shiftKey) {
      e.preventDefault();
      handleSend();
    }
  };

  // All suggestions mapped to their required tool (null = always shown)
  const allSuggestions = useMemo(() => [
    { tool: 'execute_notebook', icon: <GraduationCap size={18} />, label: 'Chấm điểm bài thi', desc: 'Tự động chấm điểm từ ảnh', prompt: 'Chấm điểm bài thi trong thư mục Filled-temp' },
    { tool: 'summarize_exam_results', icon: <FileText size={18} />, label: 'Tổng hợp kết quả', desc: 'Phân tích & báo cáo điểm', prompt: 'Tổng hợp kết quả mã đề 132' },
    { tool: 'document_query', icon: <MessageSquare size={18} />, label: 'Hỏi đáp tài liệu', desc: 'Trả lời từ nội dung bài', prompt: 'Tóm tắt nội dung chính của tài liệu đã upload' },
    { tool: 'user_guide', icon: <HelpCircle size={18} />, label: 'Hướng dẫn sử dụng', desc: 'Cách dùng các tính năng', prompt: 'Hướng dẫn tôi cách sử dụng ứng dụng' },
  ], []);

  // Filter suggestions by enabled tools
  const suggestions = useMemo(() => {
    if (!toolConfig) return allSuggestions; // show all while loading
    const enabled = new Set(toolConfig.enabled_tools);
    return allSuggestions.filter(s => s.tool === null || enabled.has(s.tool));
  }, [allSuggestions, toolConfig]);

  // Dynamic welcome message based on enabled tools
  const welcomeMessage = useMemo(() => {
    const capabilities: string[] = [];
    const enabled = toolConfig ? new Set(toolConfig.enabled_tools) : null;
    if (!enabled || enabled.has('execute_notebook')) capabilities.push('chấm điểm bài thi');
    if (!enabled || enabled.has('summarize_exam_results')) capabilities.push('phân tích kết quả');
    if (!enabled || enabled.has('document_query')) capabilities.push('hỏi đáp tài liệu');
    if (!enabled || enabled.has('user_guide')) capabilities.push('hướng dẫn sử dụng');
    if (capabilities.length === 0) return 'Tôi luôn sẵn sàng trò chuyện với bạn.';
    return `Tôi có thể giúp bạn ${capabilities.join(', ')}, và nhiều việc khác.`;
  }, [toolConfig]);

  return (
    <div className="chat-panel">
      {/* ---- Decorative background ---- */}
      <div className="chat-bg-decoration">
        <div className="chat-bg-orb chat-bg-orb-1" />
        <div className="chat-bg-orb chat-bg-orb-2" />
        <div className="chat-bg-orb chat-bg-orb-3" />
      </div>

      {/* Twinkling stars */}
      <div className="chat-stars">
        {stars.map((s) => (
          <span
            key={s.id}
            className="chat-star"
            style={{ top: s.top, left: s.left, '--duration': s.duration, '--delay': s.delay, width: s.size, height: s.size } as React.CSSProperties}
          />
        ))}
      </div>

      {/* Glow accent lines */}
      <div className="chat-glow-line chat-glow-line-1" />
      <div className="chat-glow-line chat-glow-line-2" />

      {/* ---- Header ---- */}
      <div className="chat-header">
        <div className="chat-header-left">
          <div className="chat-header-icon">
            <Sparkles size={20} />
          </div>
          <div className="chat-header-info">
            <h2>AI Teaching Assistant</h2>
            <span className="chat-header-status">
              <span className="status-dot" />
              {/* Provider Toggle Switch — hidden when only 1 provider is enabled */}
              {showProviderSwitch ? (
                <div className={`provider-switch ${switchingProvider ? 'switching' : ''}`}>
                  {isProviderEnabled('ollama') && (
                    <span className={`provider-switch-label ${config?.llm_provider !== 'groq' ? 'active' : ''}`}>
                      <Monitor size={11} /> Ollama
                    </span>
                  )}
                  <button
                    className={`provider-switch-track ${config?.llm_provider === 'groq' ? 'groq' : 'ollama'}`}
                    onClick={() => {
                      const next = config?.llm_provider === 'groq' ? 'ollama' : 'groq';
                      switchProvider(next).catch(() => {});
                    }}
                    disabled={switchingProvider || loading}
                    title={`Chuyển sang ${config?.llm_provider === 'groq' ? 'Ollama' : 'Groq'}`}
                    aria-label="Toggle LLM provider"
                  >
                    <span className="provider-switch-thumb">
                      {switchingProvider ? <RefreshCw size={10} className="spin" /> : null}
                    </span>
                  </button>
                  {isProviderEnabled('groq') && (
                    <span className={`provider-switch-label ${config?.llm_provider === 'groq' ? 'active' : ''}`}>
                      <Zap size={11} /> Groq
                    </span>
                  )}
                </div>
              ) : (
                <span className="provider-label-static">
                  {config?.llm_provider === 'groq' ? <><Zap size={11} /> Groq</> : <><Monitor size={11} /> Ollama</>}
                </span>
              )}
            </span>
          </div>
        </div>

        <div className="chat-header-actions">
          {/* Model Selector — hidden when only 1 model enabled */}
          {showModelSelector(config?.llm_provider || 'ollama') ? (
            <div className="chat-model-selector" ref={modelDropdownRef}>
              <button
                className="chat-model-trigger"
                onClick={() => setShowModelDropdown((v) => !v)}
                title="Chọn model AI"
              >
                <Sparkles size={13} className="chat-model-trigger-icon" />
                <span className="chat-model-trigger-label">{model}</span>
                <ChevronDown size={14} className={`chat-model-chevron ${showModelDropdown ? 'open' : ''}`} />
              </button>

              {showModelDropdown && (
                <div className="chat-model-dropdown">
                  <div className="chat-model-dropdown-header">
                    Chọn model
                  </div>
                  {config?.available_models.map((m) => (
                    <button
                      key={m}
                      className={`chat-model-option ${m === model ? 'active' : ''}`}
                      onClick={() => { setModel(m); setShowModelDropdown(false); }}
                    >
                      <span className="chat-model-option-name">{m}</span>
                      {m === model && <span className="chat-model-option-check">✓</span>}
                    </button>
                  ))}
                </div>
              )}
            </div>
          ) : (
            <div className="chat-model-static">
              <Sparkles size={13} />
              <span>{model}</span>
            </div>
          )}

          <button className="chat-clear-btn" onClick={clearChat} title="Xóa lịch sử chat">
            <Trash2 size={16} />
            <span>Xóa</span>
          </button>
          <PanelHelpButton panelKey="chat" />
        </div>
      </div>

      {/* ---- Messages ---- */}
      <div className="chat-messages" ref={messagesContainerRef}>
        {chatMessages.length === 0 && (
          <div className="chat-welcome">
            <div className="chat-welcome-logo">
              <div className="chat-welcome-logo-glow" />
              <div className="chat-welcome-logo-inner">
                <Bot size={32} />
              </div>
              <div className="chat-welcome-logo-ring" />
              <div className="chat-welcome-logo-ring chat-welcome-logo-ring-2" />
              <div className="chat-welcome-logo-ring chat-welcome-logo-ring-3" />
            </div>
            <h3>Xin chào! Tôi là Teaching Assistant</h3>
            {welcomeMessage && <p>{welcomeMessage}</p>}
            {suggestions.length > 0 && (
            <div className="chat-suggestions">
              {suggestions.map((s, i) => (
                <button
                  key={i}
                  className="chat-suggestion-card"
                  onClick={() => setInput(s.prompt)}
                  style={{ animationDelay: `${0.15 + i * 0.1}s` }}
                >
                  <span className="chat-suggestion-icon">{s.icon}</span>
                  <div className="chat-suggestion-text">
                    <span className="chat-suggestion-label">{s.label}</span>
                    <span className="chat-suggestion-desc">{s.desc}</span>
                  </div>
                </button>
              ))}
            </div>
            )}
          </div>
        )}

        {chatMessages.map((msg, index) => (
          <div
            key={index}
            className={`chat-msg chat-msg-${msg.role}`}
            style={{ animationDelay: `${Math.min(index * 0.05, 0.3)}s` }}
          >
            <div className="chat-msg-avatar">
              {msg.role === 'user' ? <User size={18} /> : <Bot size={18} />}
            </div>
            <div className="chat-msg-bubble">
              <pre>{renderMessageContent(msg.content, navigate)}</pre>
              <span className="chat-msg-time">
                {new Date().toLocaleTimeString('vi-VN', { hour: '2-digit', minute: '2-digit' })}
              </span>
            </div>
          </div>
        ))}

        {loading && (
          <div className="chat-msg chat-msg-assistant chat-msg-loading">
            <div className="chat-msg-avatar">
              <Bot size={18} />
            </div>
            <div className="chat-msg-bubble">
              <div className="chat-typing-indicator">
                <span /><span /><span />
              </div>
              <span className="chat-typing-text">Đang suy nghĩ...</span>
            </div>
          </div>
        )}

        <div ref={messagesEndRef} />
      </div>

      {/* Scroll to bottom */}
      {showScrollBtn && (
        <button className="chat-scroll-btn" onClick={scrollToBottom}>
          <ArrowDown size={16} />
        </button>
      )}

      {/* Tools used */}
      {chatToolsUsed.length > 0 && (
        <div className="chat-tools-bar">
          <Wrench size={14} />
          <span className="chat-tools-label">Tính năng đã dùng:</span>
          {chatToolsUsed.map((tool, index) => {
            const friendlyToolNames: Record<string, string> = {
              execute_notebook: 'Chạy notebook',
              summarize_exam_results: 'Tổng hợp kết quả',
              document_query: 'Tra cứu tài liệu',
              user_guide: 'Hướng dẫn sử dụng',
            };
            return (
              <span key={index} className="chat-tool-badge">
                {friendlyToolNames[tool.tool] || tool.tool}
              </span>
            );
          })}
        </div>
      )}

      {/* ---- Input area ---- */}
      <div className="chat-input-area">
        <div className="chat-input-wrapper">
          <textarea
            value={input}
            onChange={(e) => setInput(e.target.value)}
            onKeyPress={handleKeyPress}
            placeholder="Nhập tin nhắn cho AI Assistant..."
            rows={2}
            disabled={loading}
          />
          <button
            className="chat-send-btn"
            onClick={handleSend}
            disabled={!input.trim() || loading}
            title="Gửi tin nhắn"
          >
            {loading ? <Loader2 className="spin" size={18} /> : <Send size={18} />}
          </button>
        </div>
        <span className="chat-input-hint">Enter để gửi &middot; Shift+Enter để xuống dòng</span>
      </div>
    </div>
  );
};

export default ChatPanel;
