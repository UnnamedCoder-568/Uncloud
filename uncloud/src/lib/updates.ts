/**
 * New versions and notices.
 *
 * Two sources, kept apart on purpose. A new VERSION is found and installed by
 * the desktop shell, which verifies its signature before anything runs. A
 * NOTICE — an announcement, a known problem, a critical warning — comes from a
 * manifest the engine reads, which is data that executes nothing.
 */

import { invoke } from '@tauri-apps/api/core';
import { listen } from '@tauri-apps/api/event';
import { api, apiPost } from './sidecar';
import { inDesktop } from './platform';

export interface AppUpdateStatus {
  /** False when this build cannot verify updates, and so never checks. */
  configured: boolean;
  reason: string;
  current: string;
  available: { version: string; notes: string; date: string } | null;
}

export interface Notice {
  id: string;
  kind: string;
  title: string;
  body: string;
  severity: 'optional' | 'recommended' | 'critical';
  version: string;
  url: string;
  dismissible: boolean;
  is_application_update: boolean;
}

export interface NoticeReport {
  items: Notice[];
  critical: Notice[];
  unsupported: boolean;
  note: string;
  configured: boolean;
  enabled: boolean;
  checked_at: number | null;
  current_version: string;
}

export async function checkAppUpdate(): Promise<AppUpdateStatus | null> {
  if (!inDesktop()) return null;
  return invoke<AppUpdateStatus>('app_update_check');
}

/** Installs, then the app restarts itself. `onProgress` gets a fraction, or
 *  null while the size is not yet known. */
export async function installAppUpdate(onProgress: (fraction: number | null) => void) {
  const stop = await listen<[number, number | null]>('app-update-progress', (event) => {
    const [received, total] = event.payload;
    onProgress(total ? Math.min(1, received / total) : null);
  });
  try {
    await invoke('app_update_install');
  } finally {
    stop();
  }
}

export const getNotices = () => api<NoticeReport>('/api/updates');
export const checkNoticesNow = () => apiPost<NoticeReport>('/api/updates/check');
export const dismissNotice = (id: string) => apiPost<NoticeReport>('/api/updates/dismiss', { id });
export const setCheckUpdates = (enabled: boolean) =>
  apiPost<{ check_updates: boolean }>('/api/settings/check_updates', { enabled });

/** How often an open window checks again. The engine spaces manifest checks
 *  itself; this just keeps a window left open for days from going stale. */
export const RECHECK_MS = 6 * 60 * 60 * 1000;
