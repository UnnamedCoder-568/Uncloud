import { useState } from 'react';
import { api } from '../lib/sidecar';

export default function InferenceDiagnostics() {
  const [data, setData] = useState<unknown>(null);
  const [error, setError] = useState('');
  const [raw, setRaw] = useState(() => localStorage.getItem('uncloud.debug.raw') === 'on');
  async function refresh() {
    try { setData(await api('/api/chat/diagnostics')); setError(''); }
    catch (e) { setError(String(e)); }
  }
  return <details className="card p-4" onToggle={(e) => { if (e.currentTarget.open) void refresh(); }}>
    <summary className="cursor-pointer text-sm">Developer diagnostics</summary>
    <p className="text-xs text-[var(--text-dim)] mt-3">
      Timing and sampling for recent replies. Prompts and answers are excluded.
      Backend stages appear only when the backend reports them.
    </p>
    <label className="flex items-center gap-2 text-xs mt-3">
      <input type="checkbox" checked={raw} onChange={(e) => {
        setRaw(e.target.checked);
        localStorage.setItem('uncloud.debug.raw', e.target.checked ? 'on' : 'off');
      }} />Direct-model diagnostic mode for Chat
    </label>
    <p className="text-xs text-[var(--text-faint)] mt-2">
      Uses the conversation and native model template, with no Uncloud system prompt,
      web lookups, pictures or compacted memory. Start a new chat for a clean comparison.
    </p>
    <button className="pill mt-3" onClick={() => void refresh()}>Refresh timings</button>
    {error && <p role="alert" className="text-xs">{error}</p>}
    {data != null && <pre className="text-[11px] mt-3 overflow-auto max-h-72 whitespace-pre-wrap">
      {JSON.stringify(data, null, 2)}
    </pre>}
  </details>;
}
