/**
 * Global Confirm Modal Context
 *
 * Replaces native window.confirm() with a styled, accessible React modal.
 * Usage:
 *   const confirm = useConfirm();
 *   if (await confirm({ title: 'Xóa file?', message: '...' })) { ... }
 *
 * Returns a Promise<boolean>. true = confirmed, false = canceled / dismissed.
 *
 * Features:
 * - Esc closes (returns false)
 * - Click outside backdrop closes (returns false), unless `dismissible: false`
 * - Focuses the cancel button by default to make accidental Enter safe
 * - Supports `tone: 'danger' | 'primary'` for destructive vs neutral actions
 */
import React, {
  createContext,
  useCallback,
  useContext,
  useEffect,
  useRef,
  useState,
  type ReactNode,
} from 'react';
import { AlertTriangle, HelpCircle } from 'lucide-react';

// =============================================================================
// Types
// =============================================================================

export interface ConfirmOptions {
  title?: string;
  message: ReactNode;
  confirmLabel?: string;
  cancelLabel?: string;
  /** 'danger' shows a red confirm button + warning icon. */
  tone?: 'danger' | 'primary';
  /** If false, user can only resolve via the buttons (no Esc / backdrop). */
  dismissible?: boolean;
}

interface ConfirmContextType {
  /** Show a confirmation dialog. Resolves to true when confirmed. */
  confirm: (opts: ConfirmOptions) => Promise<boolean>;
}

// =============================================================================
// Context
// =============================================================================

const ConfirmContext = createContext<ConfirmContextType | undefined>(undefined);

// =============================================================================
// Provider
// =============================================================================

interface ActiveDialog {
  id: number;
  options: ConfirmOptions;
  resolve: (value: boolean) => void;
}

export const ConfirmProvider: React.FC<{ children: ReactNode }> = ({ children }) => {
  const [active, setActive] = useState<ActiveDialog | null>(null);
  const idRef = useRef(0);
  const cancelBtnRef = useRef<HTMLButtonElement | null>(null);

  const confirm = useCallback((options: ConfirmOptions) => {
    return new Promise<boolean>((resolve) => {
      setActive({ id: ++idRef.current, options, resolve });
    });
  }, []);

  const close = useCallback(
    (result: boolean) => {
      setActive((curr) => {
        if (curr) curr.resolve(result);
        return null;
      });
    },
    [],
  );

  // Focus the cancel button when the modal opens — destructive actions should
  // require an explicit forward step, never a stray Enter.
  useEffect(() => {
    if (active) {
      // small delay so the element is mounted
      const t = setTimeout(() => cancelBtnRef.current?.focus(), 0);
      return () => clearTimeout(t);
    }
  }, [active]);

  // Esc to cancel
  useEffect(() => {
    if (!active) return;
    if (active.options.dismissible === false) return;
    const onKey = (e: KeyboardEvent) => {
      if (e.key === 'Escape') {
        e.preventDefault();
        close(false);
      } else if (e.key === 'Enter') {
        // Enter triggers confirm only if focus is inside the dialog buttons
        // (browser default). Don't intercept here to keep button focus order.
      }
    };
    window.addEventListener('keydown', onKey);
    return () => window.removeEventListener('keydown', onKey);
  }, [active, close]);

  return (
    <ConfirmContext.Provider value={{ confirm }}>
      {children}
      {active && (
        <ConfirmDialog
          options={active.options}
          onCancel={() => close(false)}
          onConfirm={() => close(true)}
          cancelBtnRef={cancelBtnRef}
        />
      )}
    </ConfirmContext.Provider>
  );
};

// =============================================================================
// Dialog component
// =============================================================================

const ConfirmDialog: React.FC<{
  options: ConfirmOptions;
  onCancel: () => void;
  onConfirm: () => void;
  cancelBtnRef: React.RefObject<HTMLButtonElement | null>;
}> = ({ options, onCancel, onConfirm, cancelBtnRef }) => {
  const {
    title = 'Xác nhận',
    message,
    confirmLabel = 'Xác nhận',
    cancelLabel = 'Hủy',
    tone = 'primary',
    dismissible = true,
  } = options;

  const isDanger = tone === 'danger';

  return (
    <div
      className="confirm-modal-backdrop"
      onClick={dismissible ? onCancel : undefined}
      role="presentation"
      style={{
        position: 'fixed',
        inset: 0,
        background: 'rgba(15, 23, 42, 0.55)',
        backdropFilter: 'blur(2px)',
        display: 'flex',
        alignItems: 'center',
        justifyContent: 'center',
        zIndex: 9999,
        padding: '16px',
      }}
    >
      <div
        role="alertdialog"
        aria-modal="true"
        aria-labelledby="confirm-modal-title"
        aria-describedby="confirm-modal-message"
        onClick={(e) => e.stopPropagation()}
        style={{
          background: 'var(--surface, #ffffff)',
          color: 'var(--text, #0f172a)',
          borderRadius: 12,
          maxWidth: 460,
          width: '100%',
          boxShadow: '0 20px 60px rgba(15, 23, 42, 0.25)',
          overflow: 'hidden',
          display: 'flex',
          flexDirection: 'column',
        }}
      >
        <div
          style={{
            display: 'flex',
            alignItems: 'flex-start',
            gap: 12,
            padding: '20px 20px 0 20px',
          }}
        >
          <div
            aria-hidden="true"
            style={{
              flexShrink: 0,
              width: 40,
              height: 40,
              borderRadius: '50%',
              display: 'grid',
              placeItems: 'center',
              background: isDanger ? 'rgba(220, 38, 38, 0.12)' : 'rgba(59, 130, 246, 0.12)',
              color: isDanger ? '#dc2626' : '#2563eb',
            }}
          >
            {isDanger ? <AlertTriangle size={22} /> : <HelpCircle size={22} />}
          </div>
          <div style={{ flex: 1, minWidth: 0 }}>
            <h3
              id="confirm-modal-title"
              style={{ margin: 0, fontSize: 17, fontWeight: 600, lineHeight: 1.3 }}
            >
              {title}
            </h3>
            <div
              id="confirm-modal-message"
              style={{
                marginTop: 8,
                fontSize: 14,
                lineHeight: 1.5,
                color: 'var(--text-muted, #475569)',
                whiteSpace: 'pre-wrap',
              }}
            >
              {message}
            </div>
          </div>
        </div>
        <div
          style={{
            display: 'flex',
            justifyContent: 'flex-end',
            gap: 8,
            padding: 16,
            marginTop: 16,
            background: 'var(--surface-muted, rgba(15, 23, 42, 0.03))',
          }}
        >
          <button
            ref={cancelBtnRef}
            type="button"
            onClick={onCancel}
            className="btn-secondary"
            style={{
              padding: '8px 16px',
              borderRadius: 8,
              border: '1px solid var(--border, #cbd5e1)',
              background: 'var(--surface, #ffffff)',
              color: 'var(--text, #0f172a)',
              fontSize: 14,
              fontWeight: 500,
              cursor: 'pointer',
            }}
          >
            {cancelLabel}
          </button>
          <button
            type="button"
            onClick={onConfirm}
            className={isDanger ? 'btn-danger' : 'btn-primary'}
            style={{
              padding: '8px 16px',
              borderRadius: 8,
              border: 'none',
              background: isDanger ? '#dc2626' : '#2563eb',
              color: '#ffffff',
              fontSize: 14,
              fontWeight: 600,
              cursor: 'pointer',
            }}
          >
            {confirmLabel}
          </button>
        </div>
      </div>
    </div>
  );
};

// =============================================================================
// Hook
// =============================================================================

export const useConfirm = (): ConfirmContextType['confirm'] => {
  const ctx = useContext(ConfirmContext);
  if (!ctx) {
    throw new Error('useConfirm must be used within a ConfirmProvider');
  }
  return ctx.confirm;
};

export default ConfirmContext;
