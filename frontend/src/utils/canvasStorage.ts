// ============================================================================
// Canvas Token Storage Utility
// ============================================================================
// SECURITY NOTE: Using localStorage for TEMPORARY testing only.
// In production, tokens should be:
// 1. Stored server-side in encrypted database
// 2. Retrieved via authenticated session
// 3. Never exposed to client-side JavaScript
// XSS Risk: Any XSS vulnerability can steal tokens from localStorage
// ============================================================================

import type { CanvasSettings } from '../types/canvas';

const CANVAS_SETTINGS_KEY = 'canvas_settings';
const DEFAULT_CANVAS_URL = 'https://lms.uet.vnu.edu.vn';

/**
 * Get Canvas settings from localStorage
 * Returns null if not configured
 */
export function getCanvasSettings(): CanvasSettings | null {
  try {
    const stored = localStorage.getItem(CANVAS_SETTINGS_KEY);
    if (!stored) return null;
    
    const settings = JSON.parse(stored) as CanvasSettings;
    
    // Validate required fields
    if (!settings.accessToken || !settings.baseUrl) {
      return null;
    }
    
    return settings;
  } catch (error) {
    console.error('Failed to parse Canvas settings:', error);
    return null;
  }
}

/**
 * Save Canvas settings to localStorage
 */
export function saveCanvasSettings(settings: CanvasSettings): void {
  try {
    localStorage.setItem(CANVAS_SETTINGS_KEY, JSON.stringify(settings));
  } catch (error) {
    console.error('Failed to save Canvas settings:', error);
    throw new Error('Failed to save Canvas settings');
  }
}

/**
 * Update partial Canvas settings
 */
export function updateCanvasSettings(partial: Partial<CanvasSettings>): CanvasSettings {
  const current = getCanvasSettings() || {
    accessToken: '',
    baseUrl: DEFAULT_CANVAS_URL,
  };
  
  const updated: CanvasSettings = {
    ...current,
    ...partial,
  };
  
  saveCanvasSettings(updated);
  return updated;
}

/**
 * Clear Canvas settings (logout)
 */
export function clearCanvasSettings(): void {
  localStorage.removeItem(CANVAS_SETTINGS_KEY);
}

/**
 * Check if Canvas is configured
 */
export function isCanvasConfigured(): boolean {
  const settings = getCanvasSettings();
  return settings !== null && settings.accessToken.length > 0;
}

/**
 * Get Canvas access token (for API calls)
 */
export function getCanvasToken(): string | null {
  const settings = getCanvasSettings();
  return settings?.accessToken || null;
}

/**
 * Get Canvas base URL
 */
export function getCanvasBaseUrl(): string {
  const settings = getCanvasSettings();
  return settings?.baseUrl || DEFAULT_CANVAS_URL;
}

/**
 * Set selected course
 */
export function setSelectedCourse(courseId: number, courseName: string): void {
  updateCanvasSettings({
    selectedCourseId: courseId,
    selectedCourseName: courseName,
  });
}

/**
 * Get selected course
 */
export function getSelectedCourse(): { id: number; name: string } | null {
  const settings = getCanvasSettings();
  if (!settings?.selectedCourseId || !settings?.selectedCourseName) {
    return null;
  }
  return {
    id: settings.selectedCourseId,
    name: settings.selectedCourseName,
  };
}

/**
 * Clear selected course
 */
export function clearSelectedCourse(): void {
  const settings = getCanvasSettings();
  if (settings) {
    const { selectedCourseId, selectedCourseName, ...rest } = settings;
    void selectedCourseId;
    void selectedCourseName;
    saveCanvasSettings(rest as CanvasSettings);
  }
}
