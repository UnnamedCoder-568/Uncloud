import { useCallback, useEffect, useRef, useState } from 'react';
import { api, apiPost } from '../lib/sidecar';
import { useWhenVisible } from '../components/Panes';

interface Timings {
  first_token_ms?: number;
  total_ms?: number;
  stream_tokens_per_second?: number;
  usage?: { prompt_tokens?: number; completion_tokens?: number };
  runtime?: Runtime;
}
interface Runtime {
  running?: boolean;
  model_path: string;
  engine: string;
  context_limit: number;
  native?: { latest?: { ttft_s?: number; decode_tok_s?: number; prompt_tokens?: number;
    completion_tokens?: number; peak_memory_gb?: number; timestamp_unix?: number };
    server?: { apc?: { enabled?: boolean; matched_tokens?: number } } };
}
interface Run { id: string; status: string; cursor: number; error?: string; timings: Timings }

export default function BenchmarkView() {
  const [runtime, setRuntime] = useState<Runtime | null>(null);
  const [result, setResult] = useState<Timings | null>(null);
  const [running, setRunning] = useState(false);
  const [error, setError] = useState('');
  const runId = useRef<string | null>(null);
  const abort = useRef<AbortController | null>(null);
  const refresh = useCallback(() => {
    void api<Runtime>('/api/models/performance').then(value => {
      setRuntime(value); setResult(null); setError('');
    }).catch(e => setError(String(e)));
  }, []);
  useEffect(() => { refresh(); return () => { abort.current?.abort();
    if (runId.current) void api(`/api/chat/runs/${runId.current}`, { method: 'DELETE' }).catch(() => {});
  }; }, [refresh]);
  useWhenVisible(refresh);

  async function start() {
    if (runId.current) return;
    const controller = new AbortController();
    abort.current = controller;
    setRunning(true); setError('');
    try {
      let run = await apiPost<Run>('/api/models/benchmark', {}, controller.signal);
      runId.current = run.id;
      while (run.status === 'running') {
        run = await api<Run>(`/api/chat/runs/${run.id}?cursor=${run.cursor}&wait=true`, { signal: controller.signal });
      }
      if (run.status === 'error') throw new Error(run.error || 'Benchmark failed.');
      if (run.status === 'done') { setResult(run.timings); if (run.timings.runtime) setRuntime(run.timings.runtime); }
    } catch (e) {
      if (!controller.signal.aborted) setError(String(e).replace(/^Error:\s*/, ''));
    } finally {
      if (runId.current) void api(`/api/chat/runs/${runId.current}`, { method: 'DELETE' }).catch(() => {});
      runId.current = null; abort.current = null; setRunning(false);
    }
  }

  const measured = result?.runtime ?? runtime;
  const latest = measured?.native?.latest;
  const firstMs = result?.first_token_ms ?? (latest?.ttft_s == null ? null : latest.ttft_s * 1000);
  const generated = result?.usage?.completion_tokens ?? latest?.completion_tokens;
  const input = result?.usage?.prompt_tokens ?? latest?.prompt_tokens;
  const rate = latest?.decode_tok_s ?? result?.stream_tokens_per_second;
  const metrics = [
    ['First token', firstMs == null ? '—' : `${(firstMs / 1000).toFixed(2)} s`],
    ['Generation speed', rate == null ? 'Not reported' : `${rate.toFixed(1)} tokens/s`],
    ['Input tokens', input?.toLocaleString() ?? '—'],
    ['Output tokens', generated?.toLocaleString() ?? '—'],
  ];
  return <div className="h-full overflow-y-auto"><div className="page-column flex flex-col gap-6">
    <header><h2 className="page-title">Benchmark</h2>
      <p className="text-sm text-[var(--text-dim)] mt-2">Measure the loaded model on this device.</p></header>
    <section className="card p-5 flex flex-col gap-3">
      <h3 className="text-sm">{runtime?.running ? runtime.model_path.split(/[/\\]/).at(-1) : 'No text model loaded'}</h3>
      {runtime?.running && <p className="text-xs text-[var(--text-dim)]">{runtime.engine} · {runtime.context_limit.toLocaleString()} tokens loaded</p>}
      <p className="text-xs text-[var(--text-dim)]">One short local request, up to 128 output tokens, using native model defaults. Tools and conversation history are excluded. The first run may include model warm-up.</p>
      <div className="flex flex-wrap gap-2">
        <button className="pill" disabled={running || !runtime?.running} onClick={() => void start()}>{running ? 'Benchmark in progress…' : 'Run short benchmark'}</button>
        {running ? <button className="pill" onClick={() => abort.current?.abort()}>Stop</button>
          : <button className="pill" onClick={refresh}>Refresh latest reply</button>}
      </div>
      {error && <p role="alert" className="text-xs text-[var(--error)]">{error}</p>}
    </section>
    <section aria-label="Performance results" className="grid grid-cols-2 gap-3">
      {metrics.map(([label, value]) => <div key={label} className="card p-4"><p className="text-xs text-[var(--text-dim)]">{label}</p><p className="text-xl mt-2 tabular-nums">{value}</p></div>)}
    </section>
    <p className="text-xs text-[var(--text-dim)]">{result ? 'Last benchmark' : 'Latest native reply'} · First-token delay and generation speed are separate measurements. Native input counts include the chat template. Compare the same model, settings and device; close competing workloads for a controlled comparison.</p>
    {measured?.native?.server?.apc && <p className="text-xs text-[var(--text-dim)]">Prefix cache: {measured.native.server.apc.enabled ? 'enabled' : 'disabled'} · {(measured.native.server.apc.matched_tokens ?? 0).toLocaleString()} tokens reused this session</p>}
  </div></div>;
}
