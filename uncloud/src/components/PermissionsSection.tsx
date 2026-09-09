/** Settings → what Uncloud may do, and how hard it tries.
 *
 *  Two controls that sound similar and are not. Permissions decide what the
 *  agent is allowed to do; effort decides how much work it puts into doing it.
 *  They are next to each other because both answer "how much rope", and they
 *  are visually separate because confusing them means turning the wrong one
 *  down when something goes wrong.
 *
 *  The screen is honest about two limits it cannot change. Shell and delete ask
 *  every time and cannot be set to always — shown as a fixed state rather than
 *  a control that would not take. And an effort level that buys nothing with
 *  the loaded model says so, because a control that appears to work and does
 *  nothing teaches people the application is lying to them.
 */

import { useCallback, useEffect, useState } from 'react';
import { History, Lock, ShieldCheck } from 'lucide-react';

import { forgetSessionGrants, getAudit, getEffort, getPermissions,
         setEffort as saveEffort, setPermission,
         type AuditEntry, type EffortLevel,
         type PermissionsState } from '../lib/sidecar';

const CATEGORY: Record<string, string> = {
  read: 'Read files',
  write: 'Write files',
  delete: 'Delete things',
  shell: 'Run commands',
  network: 'Reach the internet',
  install: 'Install models and software',
  settings: 'Change Uncloud’s own settings',
  generate: 'Generate with a model',
  train: 'Train a model',
  device: 'Control this machine',
  message: 'Send things to other people',
};

const MODE: { id: string; label: string }[] = [
  { id: 'allow', label: 'Always' },
  { id: 'ask_category', label: 'Ask once a session' },
  { id: 'ask_once', label: 'Ask once per thing' },
  { id: 'ask', label: 'Ask every time' },
  { id: 'deny', label: 'Never' },
];

export default function PermissionsSection() {
  const [permissions, setPermissions] = useState<PermissionsState | null>(null);
  const [effort, setEffortState] = useState<
    { selected: string; levels: EffortLevel[] } | null>(null);
  const [audit, setAudit] = useState<AuditEntry[] | null>(null);
  const [busy, setBusy] = useState(false);

  const load = useCallback(() => {
    getPermissions().then(setPermissions).catch(() => undefined);
    getEffort().then(setEffortState).catch(() => undefined);
  }, []);
  useEffect(load, [load]);

  async function change(category: string, mode: string) {
    setBusy(true);
    // The response is the whole policy rather than an acknowledgement: what
    // was stored may be stricter than what was asked for, and the screen has
    // to show what took effect rather than what was pressed.
    try { setPermissions(await setPermission(category, mode)); }
    finally { setBusy(false); }
  }

  const grants = permissions
    ? permissions.session_grants.categories.length
      + permissions.session_grants.actions.length
    : 0;

  return (
    <>
      <section className="card p-4">
        <h2 className="text-sm mb-1">What Uncloud may do</h2>
        <p className="text-[11px] text-[var(--text-faint)] mb-3">
          Applies to the agent, to Chat’s own tools, and to anything a skill
          runs. Agreeing to the terms did not grant any of this.
        </p>

        <div className="flex flex-col gap-1.5">
          {permissions && Object.entries(permissions.policy).map(([category, mode]) => {
            const fixed = permissions.always_ask.includes(category);
            return (
              <div key={category}
                   className="flex items-center justify-between gap-3 px-3 py-2
                              rounded-lg hover:bg-[var(--bg-inset)] transition">
                <span className="text-xs flex items-center gap-2">
                  {CATEGORY[category] ?? category}
                  {fixed && <Lock size={11} className="text-[var(--text-faint)]" />}
                </span>
                {fixed ? (
                  <span className="text-[11px] text-[var(--text-faint)]">
                    Asks every time — cannot be changed
                  </span>
                ) : (
                  <select value={mode} disabled={busy}
                          onChange={(e) => change(category, e.target.value)}
                          className="text-[11px] bg-[var(--bg-inset)] px-2 py-1
                                     rounded-lg outline-none">
                    {MODE.map((option) => (
                      <option key={option.id} value={option.id}>{option.label}</option>
                    ))}
                  </select>
                )}
              </div>
            );
          })}
        </div>

        {grants > 0 && (
          <div className="flex items-center justify-between gap-3 mt-3 pt-3
                          border-t border-[var(--border)]">
            <span className="text-[11px] text-[var(--text-faint)]">
              {grants} thing{grants === 1 ? ' has' : 's have'} been allowed for this
              session.
            </span>
            <button onClick={async () => setPermissions(await forgetSessionGrants())}
                    className="text-[11px] px-3 py-1.5 rounded-lg
                               text-[var(--text-dim)] hover:text-[var(--text)]
                               transition">
              Forget them
            </button>
          </div>
        )}

        <button
          onClick={() => (audit ? setAudit(null)
                                : getAudit().then(setAudit).catch(() => undefined))}
          className="flex items-center gap-1.5 text-[11px] text-[var(--text-dim)]
                     hover:text-[var(--text)] transition mt-3">
          <History size={12} /> {audit ? 'Hide' : 'Show'} what has been asked
        </button>

        {audit && (
          <div className="mt-2 max-h-64 overflow-y-auto flex flex-col gap-1">
            {audit.length === 0 && (
              <p className="text-[11px] text-[var(--text-faint)]">
                Nothing has needed a decision yet.
              </p>
            )}
            {audit.map((entry, n) => (
              <div key={n} className="text-[11px] flex items-baseline gap-2">
                <span className={entry.allowed ? 'text-emerald-400' : 'text-rose-400'}>
                  {entry.allowed ? '✓' : '✕'}
                </span>
                <span className="font-mono text-[var(--text-faint)]">
                  {entry.category}
                </span>
                <span className="text-[var(--text-dim)] truncate">
                  {entry.summary || entry.action}
                </span>
              </div>
            ))}
            <p className="text-[10px] text-[var(--text-faint)] mt-1">
              Summaries only. The log records that a file was written, never what
              was written to it.
            </p>
          </div>
        )}
      </section>

      <section className="card p-4">
        <h2 className="text-sm mb-1">How hard to try</h2>
        <p className="text-[11px] text-[var(--text-faint)] mb-3">
          Separate from permissions: this is how much work goes into a task, not
          what the agent is allowed to do.
        </p>

        <div className="flex flex-col gap-1.5">
          {effort?.levels.map((level) => (
            <button key={level.id}
                    onClick={async () => setEffortState(await saveEffort(level.id))}
                    className={`text-left px-3 py-2.5 rounded-lg transition ${
                      effort.selected === level.id
                        ? 'bg-[var(--bg-inset)] ring-1 ring-[var(--accent)]'
                        : 'hover:bg-[var(--bg-inset)]'}`}>
              <div className="flex items-center gap-2">
                <span className="text-xs">{level.label}</span>
                {effort.selected === level.id && (
                  <ShieldCheck size={12} className="text-[var(--accent)]" />
                )}
              </div>
              <p className="text-[11px] text-[var(--text-faint)] mt-0.5">
                {level.blurb}
              </p>
              {level.applied.length > 0 && (
                <p className="text-[10px] text-[var(--text-dim)] mt-1 font-mono">
                  {level.applied.join(' · ')}
                </p>
              )}
              {level.degraded.length > 0 && (
                <p className="text-[10px] text-amber-400/80 mt-1">
                  Not available with the loaded model: {level.degraded.join(', ')}
                </p>
              )}
            </button>
          ))}
        </div>
      </section>
    </>
  );
}
