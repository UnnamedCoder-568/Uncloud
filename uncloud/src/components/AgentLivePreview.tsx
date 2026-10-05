import { useEffect, useRef, useState } from 'react';
import { Monitor, X } from 'lucide-react';
import { api } from '../lib/sidecar';

interface Frame { image: string; captured_at: number; source: string }

/** An explicitly authorised, transient view of this run, not a remote-control surface. */
export default function AgentLivePreview({ runId, active }: { runId: string | null; active: boolean }) {
  const [source, setSource] = useState<'browser' | 'desktop'>('browser');
  const [enabled, setEnabled] = useState(false);
  const [starting, setStarting] = useState(false);
  const [frame, setFrame] = useState<Frame | null>(null);
  const [status, setStatus] = useState('');
  const host = useRef<HTMLDivElement>(null);

  useEffect(() => {
    setEnabled(false); setFrame(null); setStatus('');
  }, [runId]);

  useEffect(() => {
    if (!runId || !active || !enabled) return;
    let stopped = false;
    let timer: ReturnType<typeof setTimeout>;
    const controller = new AbortController();
    const refresh = async () => {
      if (stopped) return;
      // Mounted inactive panes and background windows do not keep capturing.
      if (!document.hidden && host.current?.getClientRects().length) {
        try {
          const next = await api<Frame>(`/api/agent/runs/${runId}/preview`, { signal: controller.signal });
          if (!stopped) { setFrame(next); setStatus('Updating every 2 seconds'); }
        } catch (error) {
          if (stopped) return;
          const message = error instanceof Error ? error.message : 'Preview unavailable';
          setStatus(message);
          if (!message.includes('Waiting for Chisel to open its browser')) {
            setEnabled(false);
            return;
          }
        }
      }
      timer = setTimeout(refresh, 2000);
    };
    void refresh();
    return () => {
      stopped = true; controller.abort(); clearTimeout(timer);
      void api(`/api/agent/runs/${runId}/preview`, { method: 'DELETE' }).catch(() => {});
    };
  }, [runId, active, enabled]);

  if (!active || !runId) return null;
  return <aside ref={host} aria-label="Live Chisel preview" style={{
    position: 'absolute', right: 20, bottom: 110, width: 'min(360px, calc(100% - 40px))',
    zIndex: 20, border: '1px solid var(--border)', borderRadius: 16,
    background: 'var(--surface)', boxShadow: 'var(--shadow-lg)', overflow: 'hidden',
  }}>
    <div style={{ display: 'flex', alignItems: 'center', gap: 8, padding: '10px 12px' }}>
      <Monitor size={15} /><span style={{ flex: 1, fontSize: 12 }}>Live activity</span>
      {enabled && <button className="pill pill-icon" title="Stop preview" aria-label="Stop preview"
        onClick={() => setEnabled(false)}><X size={14} /></button>}
    </div>
    {frame && <img src={`data:image/jpeg;base64,${frame.image}`} alt={`${frame.source} preview`}
      style={{ display: 'block', width: '100%', maxHeight: 225, objectFit: 'contain', background: '#111' }} />}
    {!enabled && <div style={{ display: 'flex', gap: 8, padding: '0 12px 12px', alignItems: 'center' }}>
      <select aria-label="Preview source" value={source} disabled={starting} onChange={(event) => {
        setSource(event.target.value as 'browser' | 'desktop'); setFrame(null);
      }}><option value="browser">Agent browser</option><option value="desktop">This device</option></select>
      <button className="pill" disabled={starting} onClick={async () => {
        setStarting(true); setStatus('Requesting preview access…');
        try {
          await api(`/api/agent/runs/${runId}/preview`, { method: 'POST', body: JSON.stringify({ source }) });
          setEnabled(true);
        } catch (error) { setStatus(error instanceof Error ? error.message : 'Preview unavailable'); }
        finally { setStarting(false); }
      }}>{starting ? 'Connecting…' : 'Show preview'}</button>
    </div>}
    <div role="status" style={{ fontSize: 11, color: 'var(--text-3)', padding: '0 12px 12px', overflowWrap: 'anywhere' }}>
      {status || 'Preview starts only after you allow it.'}
      {frame && <span style={{ display: 'block' }}>Last captured {new Date(frame.captured_at * 1000).toLocaleTimeString()}</span>}
    </div>
  </aside>;
}
