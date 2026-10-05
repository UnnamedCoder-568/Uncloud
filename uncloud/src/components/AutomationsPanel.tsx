import { useEffect, useState } from 'react';
import { Clock } from 'lucide-react';
import { api, apiPost, getLibrary } from '../lib/sidecar';
import type { LocalModel } from '../lib/sidecar';
type Graph = { tasks?: Record<string, { description: string; status: string; output?: string; error?: string }> };
type Agent = { id: string; goal: string; status: string; paused: boolean; next_run: number; message: string; progress?: Graph; history: { started: number; status: string; graph?: Graph }[] };
const files = ['fs_read', 'fs_list', 'fs_glob', 'fs_grep', 'plan_show', 'note_recall', 'skill_list', 'skill_read'];
export default function AutomationsPanel() {
  const [open, setOpen] = useState(false), [items, setItems] = useState<Agent[]>([]), [models, setModels] = useState<LocalModel[]>([]);
  const [firstRun, setFirstRun] = useState('');
  const [goal, setGoal] = useState(''), [path, setPath] = useState(''), [interval, setPeriod] = useState(0), [web, setWeb] = useState(false), [error, setError] = useState(''), [busy, setBusy] = useState(false);
  async function refresh() { const r = await api<{ items: Agent[]; error: string }>('/api/automations'); setItems(r.items); setError(r.error); }
  useEffect(() => {
    if (!open) return;
    let alive = true;
    const poll = async () => {
      if (document.hidden || document.querySelector('[data-automations-panel]')?.closest('[hidden]')) return;
      try { const r = await api<{ items: Agent[]; error: string }>('/api/automations'); if (alive) { setItems(r.items); setError(r.error); } } catch (e) { if (alive) setError(String(e)); }
    };
    void poll(); void getLibrary().then(ms => { if (alive) setModels(ms.filter(m => m.category === 'text' && m.ready)); }).catch(e => { if (alive) setError(String(e)); });
    const timer = window.setInterval(poll, 3000); return () => { alive = false; clearInterval(timer); };
  }, [open]);
  async function act(id: string, action: string) { setBusy(true); try { await apiPost(`/api/automations/${id}/${action}`); await refresh(); } catch (e) { setError(String(e)); } finally { setBusy(false); } }
  return <div data-automations-panel className="mt-3">
    <button className="pill h-8 px-3 text-xs" aria-expanded={open} onClick={() => setOpen(!open)}><Clock size={14} /> Saved agents & schedules</button>
    {open && <section className="mt-3 rounded-xl border border-[var(--border-soft)] bg-[var(--bg-inset)] p-4 max-h-[55vh] overflow-y-auto space-y-4">
      <p className="text-xs text-[var(--text-faint)]">Runs while Uncloud is open, one agent at a time. File access stays inside the Uncloud workspace. Writes and device control need interactive Chisel.</p>
      <form className="space-y-3" onSubmit={async e => {
        e.preventDefault(); const model = models.find(m => m.path === path); if (!model) return; setBusy(true);
        try { await apiPost('/api/automations', { goal, model_path: path, engine: model.engine, interval, next_run: firstRun ? new Date(firstRun).getTime() / 1000 : 0, tools: [...files, ...(web ? ['web_search', 'web_read', 'http_fetch'] : [])] }); setGoal(''); await refresh(); } catch (e) { setError(String(e)); } finally { setBusy(false); }
      }}>
        <label className="block text-xs">Goal<textarea required maxLength={8000} value={goal} onChange={e => setGoal(e.target.value)} placeholder="Describe a task to repeat or continue later…" className="mt-1 w-full rounded-lg bg-[var(--surface)] p-3 text-sm resize-y min-h-20" /></label>
        <div className="flex flex-wrap gap-3">
          <label className="text-xs flex-1 min-w-40">Model<select required value={path} onChange={e => setPath(e.target.value)} className="block w-full mt-1 rounded-lg bg-[var(--surface)] p-2"><option value="">Choose an installed model</option>{models.map(m => <option key={m.path} value={m.path}>{m.name}</option>)}</select></label>
          <label className="text-xs">Schedule<select value={interval} onChange={e => setPeriod(Number(e.target.value))} className="block mt-1 rounded-lg bg-[var(--surface)] p-2"><option value={0}>Run once now</option><option value={3600}>Every hour</option><option value={86400}>Every day</option><option value={604800}>Every week</option></select></label>
        </div>
        <label className="block text-xs">First run (leave blank to start now)<input type="datetime-local" value={firstRun} onChange={e => setFirstRun(e.target.value)} className="block mt-1 rounded-lg bg-[var(--surface)] p-2" /></label>
        <label className="flex gap-2 items-center text-xs"><input type="checkbox" checked={web} onChange={e => setWeb(e.target.checked)} /> Include web research (network permission still applies)</label>
        <p className="text-xs text-[var(--text-faint)]">Agents start at your chosen time and repeat after each completed run. Missed runs are not replayed in a burst.</p>
        <button className="pill h-8 px-3 text-xs" disabled={busy || !goal.trim() || !path}>Save agent</button>
      </form>
      {error && <p role="alert" className="text-xs text-amber-400">{error}</p>}
      {!items.length && <p className="text-xs text-[var(--text-faint)]">No saved agents yet.</p>}
      {items.map(item => <article key={item.id} className="border-t border-[var(--border-soft)] pt-3 space-y-2">
        <p className="text-sm whitespace-pre-wrap">{item.goal}</p><p className="text-xs text-[var(--text-faint)]"><span aria-hidden className={`inline-block w-1.5 h-1.5 rounded-full mr-1.5 ${item.status === 'running' ? 'bg-emerald-400' : 'bg-[var(--text-faint)]'}`} />{item.status.replaceAll('_', ' ')}{!item.paused && item.status !== 'running' ? ` · Next: ${new Date(item.next_run * 1000).toLocaleString()}` : ''}</p>
        {item.message && <p className="text-xs text-amber-400">{item.message}</p>}
        <div className="flex gap-2"><button className="pill h-7 px-2 text-xs" disabled={busy} onClick={() => void act(item.id, item.paused ? 'resume' : 'pause')}>{item.paused ? 'Resume' : 'Pause'}</button><button className="pill h-7 px-2 text-xs" disabled={busy || item.status === 'running'} onClick={() => void act(item.id, 'run')}>Run fresh</button><button className="pill h-7 px-2 text-xs" disabled={busy} onClick={() => { if (window.confirm('Delete this saved agent and its history?')) void act(item.id, 'delete'); }}>Delete</button></div>
        <details className="text-xs"><summary className="cursor-pointer text-[var(--text-faint)]">Progress & run history ({item.history.length})</summary>{[...(item.progress ? [{ started: 0, status: 'Current progress', graph: item.progress }] : []), ...item.history.slice().reverse()].map((run, i) => <div key={i} className="mt-2 space-y-1"><p>{run.started ? new Date(run.started * 1000).toLocaleString() : ''} · {run.status}</p>{Object.entries(run.graph?.tasks ?? {}).map(([id, task]) => <details key={id} className="pl-2"><summary>{task.status} · {task.description}</summary><pre className="whitespace-pre-wrap break-words max-h-48 overflow-y-auto">{task.error || task.output || 'No result yet'}</pre></details>)}</div>)}</details>
      </article>)}
    </section>}
  </div>;
}
