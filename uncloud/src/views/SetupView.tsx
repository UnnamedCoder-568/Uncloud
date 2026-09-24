import ActivityOrb from '../components/ActivityOrb';
import { useEffect, useRef, useState } from 'react';
import { listen } from '@tauri-apps/api/event';
import { Check, Download, AlertCircle } from 'lucide-react';
import { runtimeStatus, installRuntime, startRuntime } from '../lib/sidecar';
import type { RuntimeStatus } from '../lib/sidecar';
import Wordmark from '../components/Wordmark';

type Phase = 'checking' | 'ready-to-install' | 'installing' | 'starting' | 'failed';

/**
 * Shown when the engine isn't running. Uncloud's interface ships as a small
 * desktop app; the Python engine that actually runs the models is installed
 * here, on first launch, rather than being frozen into the installer.
 */
export default function SetupView({ onReady }: { onReady: () => void }) {
  const [phase, setPhase] = useState<Phase>('checking');
  const [status, setStatus] = useState<RuntimeStatus | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [log, setLog] = useState<string[]>([]);
  const logEnd = useRef<HTMLDivElement>(null);

  useEffect(() => {
    const unlisten = listen<string>('runtime-install-log', (e) => {
      // uv is chatty; keep the tail bounded so this never grows without limit.
      setLog((prev) => [...prev.slice(-400), e.payload]);
    });
    return () => { unlisten.then((f) => f()); };
  }, []);

  useEffect(() => {
    logEnd.current?.scrollIntoView({ behavior: 'smooth' });
  }, [log]);

  useEffect(() => {
    runtimeStatus()
      .then((s) => {
        setStatus(s);
        if (s.running) onReady();
        else setPhase('ready-to-install');
      })
      .catch((e) => { setError(String(e)); setPhase('failed'); });
  }, [onReady]);

  async function run() {
    setError(null);
    setLog([]);
    try {
      if (!status?.deps_ready) {
        setPhase('installing');
        await installRuntime();
      }
      setPhase('starting');
      await startRuntime();
      onReady();
    } catch (e) {
      setError(String(e).replace(/^Error:\s*/, ''));
      setPhase('failed');
      setStatus(await runtimeStatus().catch(() => status));
    }
  }

  const busy = phase === 'installing' || phase === 'starting';

  const checks = status ? [
    { label: 'Engine files', ok: status.source_ready,
      detail: status.source_ready ? status.engine_dir : 'Not found in this build' },
    { label: 'uv (package manager)', ok: status.uv_found,
      detail: status.uv_found ? 'Found' : 'Not installed' },
    { label: 'Dependencies', ok: status.deps_ready,
      detail: status.deps_ready ? 'Installed' : 'Several GB, downloaded once' },
  ] : [];

  return (
    <div className="h-screen w-screen overflow-y-auto bg-[var(--bg)]">
      <div className="max-w-lg mx-auto px-8 py-14">
        <div className="flex items-center gap-3">
          {busy && <ActivityOrb state="connecting" size={32} label="Installing the engine…" />}
          <Wordmark size={28} />
        </div>

        <h1 className="mt-8 text-xl font-semibold">Set up the engine</h1>
        <p className="mt-2 text-sm text-[var(--text-dim)] leading-relaxed">
          Uncloud ships as a small app. The engine that runs the models is
          installed here on first launch, so the download stays a few megabytes
          instead of a few gigabytes. This happens once and needs an internet
          connection; Python and the package manager are already included.
        </p>

        <div className="mt-6 card p-4 flex flex-col gap-3">
          {checks.map((c) => (
            <div key={c.label} className="flex items-start gap-3">
              <div className={`mt-0.5 shrink-0 ${c.ok ? 'text-emerald-400' : 'text-[var(--text-faint)]'}`}>
                {c.ok ? <Check size={14} strokeWidth={2.5} />
                      : busy ? <ActivityOrb state="working" size={20} label="Working…" />
                      : <div className="w-[14px] h-[14px] rounded-full border border-current" />}
              </div>
              <div className="min-w-0">
                <div className="text-xs font-medium">{c.label}</div>
                <div className="text-[11px] text-[var(--text-faint)] truncate">{c.detail}</div>
              </div>
            </div>
          ))}
        </div>

        {error && (
          <div className="mt-4 card p-4 border-rose-500/30">
            <div className="flex items-center gap-2 text-rose-400">
              <AlertCircle size={14} />
              <span className="text-xs font-medium">Setup didn't finish</span>
            </div>
            <p className="mt-2 text-[11px] text-[var(--text-dim)] whitespace-pre-wrap leading-relaxed">
              {error}
            </p>
            {status && !status.uv_found && (
              <p className="mt-2 text-[11px] text-[var(--text-dim)] leading-relaxed">
                Install <span className="font-mono">uv</span> and reopen Uncloud:
                <span className="block mt-1 font-mono text-[10px] bg-[var(--bg-inset)] rounded px-2 py-1.5">
                  curl -LsSf https://astral.sh/uv/install.sh | sh
                </span>
              </p>
            )}
          </div>
        )}

        <button
          onClick={run}
          disabled={busy || phase === 'checking'}
          className="mt-5 w-full h-11 rounded-xl btn-accent text-sm font-medium flex items-center justify-center gap-2 disabled:opacity-30 transition"
        >
          {busy ? <ActivityOrb state="working" size={20} label="Working…" /> : <Download size={15} />}
          {phase === 'installing' ? 'Installing…'
            : phase === 'starting' ? 'Starting the engine…'
            : phase === 'failed' ? 'Try again'
            : 'Install and start'}
        </button>

        {log.length > 0 && (
          <div className="mt-4 card p-3 max-h-56 overflow-y-auto">
            <pre className="text-[10px] leading-relaxed text-[var(--text-faint)] font-mono whitespace-pre-wrap break-all">
              {log.join('\n')}
            </pre>
            <div ref={logEnd} />
          </div>
        )}

        <p className="mt-6 text-[11px] text-[var(--text-faint)] leading-relaxed">
          Music and narration need extra environments and are installed
          separately, the first time you open those tabs.
        </p>
      </div>
    </div>
  );
}
