import { useCallback, useEffect, useState, type ReactNode } from 'react';
import { apiPost, getReadiness, installCapability, type CapabilityReady } from '../lib/sidecar';
import { useWhenVisible } from './Panes';
import ActivityOrb from './ActivityOrb';
import StartupScreen from './StartupScreen';
import { libraryChanged } from '../lib/library-changed';

export default function CapabilityGate({ names = '', children, setup = false }: {
  names?: string; children: ReactNode; setup?: boolean;
}) {
  const [rows, setRows] = useState<CapabilityReady[] | null>(null);
  const [busy, setBusy] = useState(false);
  const [setupDone, setSetupDone] = useState(false);
  const [error, setError] = useState('');
  const [log, setLog] = useState<string[]>([]);
  const refresh = useCallback(async () => {
    try { setRows(await getReadiness(names)); setError(''); }
    catch (e) { setError(String(e)); }
  }, [names]);
  useEffect(() => { setRows(null); void refresh(); }, [refresh]);
  useWhenVisible(() => { void refresh(); });
  const missing = rows?.filter((row) => row.supported && !row.ready) ?? [];
  const unsupported = rows?.filter((row) => !row.supported) ?? [];
  async function repair() {
    setBusy(true); setError(''); setLog([]);
    const errors: string[] = [];
    for (const row of missing) {
      try {
        await installCapability(row.id, (line) => setLog((old) => [...old.slice(-80), line]));
      } catch (e) { errors.push(`${row.label}: ${String(e)}`); }
    }
    await refresh();
    setError(errors.join('\n'));
    setBusy(false);
    libraryChanged();
  }
  if (setup && setupDone) return <>{children}</>;
  if (!setup && rows && !missing.length && (setup || !unsupported.length) && !busy && !error) return <>{children}</>;
  const content = <>
    {!setup && (!rows || busy) && <ActivityOrb size={64} state="connecting" label={busy ? 'Installing and verifying…' : 'Checking requirements…'} />}
    {!setup && <h2 className="text-lg">{busy ? 'Installing and verifying' : 'Prepare this feature'}</h2>}
    {(!setup || !!missing.length) && <p className="text-sm text-[var(--text-dim)]">{rows ? 'Install the software below to use these features. Models are downloaded separately.' : 'Checking the software this computer needs…'}</p>}
    {rows?.filter((row) => !row.ready).map((row) => <div key={row.id} className="card p-3 w-full max-w-lg text-left">
      <strong className="text-sm">{row.label}</strong><p className="text-xs text-[var(--text-dim)]">{row.detail}</p>
    </div>)}
    {error && <p role="alert" className="text-sm text-rose-400 whitespace-pre-wrap">{error}</p>}
    {!!missing.length && <button disabled={busy} onClick={repair} className="btn-accent rounded-lg px-5 py-2 disabled:opacity-40">{busy ? 'Installing…' : 'Install / Repair required software'}</button>}
    {setup && rows && !busy && <button className="btn-accent rounded-lg px-5 py-2" onClick={async () => {
      try { await apiPost('/api/readiness/complete'); setSetupDone(true); }
      catch (e) { setError(String(e)); }
    }}>{missing.length ? 'Continue with ready features; repair others in their tabs' : 'Continue'}</button>}
    {!busy && <button onClick={refresh} className="text-sm underline">Check again</button>}
    {!!log.length && <details className="w-full max-w-lg text-left"><summary>Installation details</summary><pre className="text-xs whitespace-pre-wrap max-h-60 overflow-auto">{log.join('\n')}</pre></details>}
  </>;
  if (setup) return <StartupScreen status={busy ? 'Installing your local AI tools…'
    : !rows ? 'Checking that your AI tools are ready…'
    : error ? 'Setup needs your attention'
    : missing.length ? 'A few tools need to be installed'
    : 'Your workspace is ready'}>{content}</StartupScreen>;
  return <div className="h-full overflow-auto p-8 flex flex-col items-center gap-4 text-center">{content}</div>;
}
