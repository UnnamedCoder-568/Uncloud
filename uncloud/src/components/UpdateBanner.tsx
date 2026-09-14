/**
 * The one strip across the top that says something has changed.
 *
 * Shown for three things only: a newer Uncloud that is ready to install, a
 * critical notice, and a recommended one. Optional notices live in Settings —
 * a banner for every announcement is how a banner stops being read.
 *
 * Nothing here installs by itself. The update is downloaded and installed when
 * a person presses the button, and a critical notice is a notice, not an
 * action taken on their behalf.
 */

import { useCallback, useEffect, useState } from 'react';
import { AlertTriangle, ArrowUpCircle, Info, Loader2, X } from 'lucide-react';
import { getSettings } from '../lib/sidecar';
import { inDesktop } from '../lib/platform';
import {
  RECHECK_MS, checkAppUpdate, dismissNotice, getNotices, installAppUpdate,
} from '../lib/updates';
import type { AppUpdateStatus, Notice } from '../lib/updates';

export default function UpdateBanner() {
  const [app, setApp] = useState<AppUpdateStatus | null>(null);
  const [notices, setNotices] = useState<Notice[]>([]);
  const [installing, setInstalling] = useState(false);
  const [progress, setProgress] = useState<number | null>(null);
  const [error, setError] = useState<string | null>(null);

  const check = useCallback(async () => {
    try {
      const settings = await getSettings();
      const report = await getNotices();
      setNotices(report.items.filter((n) => n.severity !== 'optional' && !n.is_application_update));
      if (settings.check_updates) setApp(await checkAppUpdate());
    } catch {
      // An update check that cannot run has found nothing wrong with the app.
    }
  }, []);

  useEffect(() => {
    if (!inDesktop()) return;
    check();
    const timer = setInterval(check, RECHECK_MS);
    return () => clearInterval(timer);
  }, [check]);

  async function install() {
    setInstalling(true);
    setError(null);
    try {
      await installAppUpdate(setProgress);
    } catch (e) {
      setError(String(e));
      setInstalling(false);
    }
  }

  async function dismiss(id: string) {
    const report = await dismissNotice(id);
    setNotices(report.items.filter((n) => n.severity !== 'optional' && !n.is_application_update));
  }

  const available = app?.available;
  if (!available && notices.length === 0) return null;

  return (
    <div className="flex flex-col">
      {available && (
        <div className="flex flex-wrap items-center gap-x-3 gap-y-1 px-4 py-2 border-b border-[var(--border-soft)] bg-[var(--bg-raised)] text-[12px]">
          <ArrowUpCircle size={14} className="text-[var(--accent)] shrink-0" />
          <span className="text-[var(--text-dim)] min-w-0">
            <strong className="text-white font-medium">Uncloud {available.version}</strong> is ready to install
            {available.notes && <span className="text-[var(--text-faint)]"> — {available.notes.split('\n')[0]}</span>}
          </span>
          <span className="flex-1" />
          {error && <span className="text-rose-400">{error}</span>}
          <button onClick={install} disabled={installing}
                  className="btn-accent text-xs px-3 py-1 rounded-lg flex items-center gap-1.5 disabled:opacity-60 max-md:min-h-11">
            {installing && <Loader2 size={12} className="animate-spin" />}
            {installing
              ? progress === null ? 'Downloading…' : `Downloading ${Math.round(progress * 100)}%`
              : 'Install and restart'}
          </button>
        </div>
      )}
      {notices.map((notice) => (
        <div key={notice.id}
             className={`flex flex-wrap items-start gap-x-3 gap-y-1 px-4 py-2 border-b border-[var(--border-soft)] text-[12px] ${
               notice.severity === 'critical' ? 'bg-rose-950/40' : 'bg-[var(--bg-raised)]'}`}>
          {notice.severity === 'critical'
            ? <AlertTriangle size={14} className="text-rose-400 shrink-0 mt-0.5" />
            : <Info size={14} className="text-[var(--text-dim)] shrink-0 mt-0.5" />}
          <span className="min-w-0 flex-1 text-[var(--text-dim)]">
            <strong className="text-white font-medium">{notice.title}</strong>
            {notice.body && <span> — {notice.body}</span>}
            {notice.url && (
              <a href={notice.url} target="_blank" rel="noopener noreferrer"
                 className="ml-1.5 underline text-[var(--text-dim)] hover:text-white">More</a>
            )}
          </span>
          {notice.dismissible && (
            <button onClick={() => dismiss(notice.id)} className="tb-btn" aria-label="Dismiss">
              <X size={13} />
            </button>
          )}
        </div>
      ))}
    </div>
  );
}
