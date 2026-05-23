import { useEffect } from 'react';

/**
 * Listen for the Escape key while `enabled` is true and invoke `onEscape`.
 *
 * Useful for closing modals/dialogs without writing the boilerplate
 * keydown listener in every component.
 *
 * The handler is registered with `capture: true` so it runs before any
 * inner element that might `stopPropagation()` (e.g. an embedded textarea).
 */
export function useEscapeKey(onEscape: () => void, enabled: boolean = true): void {
  useEffect(() => {
    if (!enabled) return;
    const handler = (e: KeyboardEvent) => {
      if (e.key === 'Escape') {
        e.stopPropagation();
        onEscape();
      }
    };
    window.addEventListener('keydown', handler, true);
    return () => window.removeEventListener('keydown', handler, true);
  }, [onEscape, enabled]);
}
