/**
 * Settings: which version this is, whether it looks for newer ones, and every
 * notice — including the optional ones the banner leaves out.
 */

import { useEffect, useState } from 'react';
import { ArrowUpCircle, Loader2, RefreshCw } from 'lucide-react';
import { getSettings } from '../lib/sidecar';
import { inDesktop } from '../lib/platform';
import {
  checkAppUpdate, checkNoticesNow, dismissNotice, getNotices, installAppUpdate, setCheckUpdates,
} from '../lib/updates';
import type { AppUpdateStatus, NoticeReport } from '../lib/updates';

export default function UpdatesSection() {
  const [enabled, setEnabled] = useState<boolean | null>(null);
  const [app, setApp] = useState<AppUpdateStatus | null>(null);
  const [report, setReport] = useState<NoticeReport | null>(null);
  const [checking, setChecking] = useState(false);
  const [installing, setInstalling] = useState(false);
  const [progress, setProgress] = useState<number | null>(null);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    getSettings().then((s) => setEnabled(s.check_updates)).catch(() => undefined);
    getNotices().then(setReport).catch(() => undefined);
  }, []);

  async function checkNow() {
    setChecking(true);
    setError(null);
    try {
      const [status, notices] = await Promise.all([checkAppUpdate(), checkNoticesNow()]);
      setApp(status);
      setReport(notices);
    } catch (e) {
      setError(String(e));
    } finally {
      setChecking(false);
    }
  }

  async function toggle() {
    const next = !enabled;
    await setCheckUpdates(next);
    setEnabled(next);
  }

  async function install() {
    setInstalling(true);
    try { await installAppUpdate(setProgress); }
    catch (e) { setError(String(e)); setInstalling(false); }
  }

  if (!inDesktop()) return null;

  return (
    <section className="card p-4">
      <div className="flex items-start justify-between gap-4">
        <div>
          <h2 className="text-sm mb-1">Updates</h2>
          <p className="text-[11px] text-[var(--text-faint)] max-w-sm">
            This is Uncloud {report?.current_version || app?.current || ''}. Checking asks GitHub
            whether a newer version or a notice exists. Nothing about this computer is sent, and
            nothing installs until you press Install.
          </p>
        </div>
        {enabled !== null && (
          <button onClick={toggle} aria-label={enabled ? 'Stop checking automatically' : 'Check automatically'}
                  className={`w-11 h-6 rounded-full shrink-0 transition relative ${enabled ? 'accent-bar' : 'bg-[var(--border)]'}`}>
            <span className={`absolute top-0.5 w-5 h-5 rounded-full bg-white transition ${enabled ? 'left-5' : 'left-0.5'}`} />
          </button>
        )}
      </div>

      <div className="mt-3 flex flex-wrap items-center gap-3 text-[12px]">
        <button onClick={checkNow} disabled={checking}
                className="text-xs px-3 py-1.5 rounded-lg bg-[var(--bg-inset)] text-[var(--text-dim)] hover:text-white transition flex items-center gap-1.5 disabled:opacity-60 max-md:min-h-11">
          {checking ? <Loader2 size={12} className="animate-spin" /> : <RefreshCw size={12} />} Check now
        </button>
        {report?.checked_at && (
          <span className="text-[11px] text-[var(--text-faint)]">
            Last checked {new Date(report.checked_at * 1000).toLocaleString()}
          </span>
        )}
      </div>

      {app && !app.configured && (
        <p className="mt-3 text-[11px] text-amber-400/80">{app.reason}</p>
      )}
      {app?.configured && app.reason && (
        <p className="mt-3 text-[11px] text-[var(--text-faint)]">{app.reason}</p>
      )}
      {app?.configured && !app.available && !app.reason && (
        <p className="mt-3 text-[11px] text-[var(--text-faint)]">You have the newest version.</p>
      )}
      {app?.available && (
        <div className="mt-3 flex flex-wrap items-center gap-3 text-[12px]">
          <ArrowUpCircle size={14} className="text-[var(--accent)]" />
          <span>Uncloud {app.available.version} is available.</span>
          <button onClick={install} disabled={installing}
                  className="btn-accent text-xs px-3 py-1.5 rounded-lg flex items-center gap-1.5 disabled:opacity-60 max-md:min-h-11">
            {installing && <Loader2 size={12} className="animate-spin" />}
            {installing ? (progress === null ? 'Downloading…' : `${Math.round(progress * 100)}%`) : 'Install and restart'}
          </button>
        </div>
      )}
      {report?.unsupported && (
        <p className="mt-3 text-[11px] text-rose-400">
          This version is no longer supported. Install the newest version to keep receiving fixes.
        </p>
      )}

      {report && report.items.filter((n) => !n.is_application_update).length > 0 && (
        <div className="mt-4 flex flex-col gap-2">
          {report.items.filter((n) => !n.is_application_update).map((n) => (
            <div key={n.id} className="text-[12px] border-t border-[var(--border-soft)] pt-2 flex items-start justify-between gap-3">
              <div className="min-w-0">
                <div className={n.severity === 'critical' ? 'text-rose-400' : 'text-white'}>{n.title}</div>
                {n.body && <div className="text-[11px] text-[var(--text-faint)] mt-0.5">{n.body}</div>}
                {n.url && <a href={n.url} target="_blank" rel="noopener noreferrer" className="text-[11px] underline text-[var(--text-dim)]">More</a>}
              </div>
              {n.dismissible && (
                <button onClick={() => dismissNotice(n.id).then(setReport)}
                        className="text-[11px] text-[var(--text-faint)] hover:text-[var(--text-dim)] shrink-0 max-md:min-h-11">
                  Dismiss
                </button>
              )}
            </div>
          ))}
        </div>
      )}
      {error && <p className="mt-3 text-[11px] text-rose-400">{error}</p>}
    </section>
  );
}
