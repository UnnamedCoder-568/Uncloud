import { useCallback, useEffect, useState } from 'react';
import { Bell, X } from 'lucide-react';
import { listen } from '@tauri-apps/api/event';
import { invoke } from '@tauri-apps/api/core';
import { api, apiPost } from '../lib/sidecar';
import { inDesktop } from '../lib/platform';
import { useDismiss } from '../lib/useDismiss';
import type { View } from './Sidebar';

export interface UserEvent { id: string; category: string; title: string; body: string; target: View;
  run_id: string; request_id: string; conversation_id: string; created: number; read: boolean; delivery: string; }
interface Interaction { id: string; run_id: string; kind: 'permission' | 'question'; status: string;
  expires: number; details: { category?: string; summary?: string; preview?: Record<string, unknown>;
    question?: string; options?: string[] }; }
interface AgentRun { id: string; status: string; graph?: Record<string, unknown>; updated: number; error?: string }
export interface NotificationReport { events: UserEvent[]; requests: Interaction[]; runs: AgentRun[];
  storage_error?: string;
  preferences: NotificationPreferences; }
export interface NotificationPreferences { enabled: boolean; sound: boolean; system_sound: boolean;
  background: boolean; quiet: boolean; categories: Record<string, boolean>; }
export const getNotifications = () => api<NotificationReport>('/api/notifications');

export default function NotificationCenter({ navigate }: { navigate: (view: View) => void }) {
  const [report, setReport] = useState<NotificationReport | null>(null);
  const [open, setOpen] = useState(false);
  const [filter, setFilter] = useState('all');
  const [error, setError] = useState('');
  const [answers, setAnswers] = useState<Record<string, string>>({});
  const [submitting, setSubmitting] = useState<string | null>(null);
  const ref = useDismiss(open, () => setOpen(false));
  const refresh = useCallback(async () => { const report = await getNotifications(); setReport(report);
    window.dispatchEvent(new CustomEvent('uncloud.agent-progress', { detail: report.runs })); }, []);
  const openEvent = useCallback(async (id: string) => {
    // Resolve the native ID against authenticated history. The event cannot
    // supply an arbitrary URL, permission answer or command to execute.
    const history = await getNotifications();
    const event = history.events.find(e => e.id === id);
    setReport(history);
    if (!event) return;
    const destinations: View[] = ['chat', 'chisel', 'automations', 'models', 'settings', 'image', 'video', 'music', 'voice'];
    if (!destinations.includes(event.target)) return;
    navigate(event.target);
    if (event.conversation_id) window.dispatchEvent(new CustomEvent('uncloud.open-conversation', { detail: event.conversation_id }));
    if (event.request_id || event.target === 'chisel') setOpen(true);
    await apiPost('/api/notifications/mark', { operation: 'read', id });
    await refresh();
  }, [navigate, refresh]);
  useEffect(() => {
    void refresh().catch(() => {});
    const timer = setInterval(() => { if (document.visibilityState !== 'hidden') void refresh().catch(() => {}); }, 4000);
    const foreground = () => { void refresh().catch(() => {}); };
    window.addEventListener('focus', foreground);
    const interaction = () => { setOpen(true); foreground(); };
    window.addEventListener('uncloud.interaction', interaction);
    let unlisten: (() => void) | undefined;
    let alive = true;
    if (inDesktop()) {
      void listen<string>('notification-open', e => { void openEvent(e.payload).catch(() => {}); }).then(off => { if (alive) unlisten = off; else off(); });
      void invoke<{ last_click?: string }>('desktop_preferences', { consume: true }).then(p => { if (p.last_click) void openEvent(p.last_click); }).catch(() => {});
    }
    return () => { alive = false; clearInterval(timer); unlisten?.(); window.removeEventListener('focus', foreground); window.removeEventListener('uncloud.interaction', interaction); };
  }, [refresh, openEvent]);

  const respond = async (request: Interaction, answer: string) => {
    if (submitting) return;
    setSubmitting(request.id); setError('');
    try { await apiPost(`/api/interactions/${request.id}/answer`, { answer }); await refresh(); }
    catch (e) { setError(e instanceof Error ? e.message : String(e)); }
    finally { setSubmitting(null); }
  };
  // The server resolves expiry using its clock and rejects every stale answer.
  const pending = report?.requests.filter(r => r.status === 'pending') ?? [];
  const unread = report?.events.filter(e => !e.read).length ?? 0;
  return <div className="relative shrink-0" ref={ref}>
    <button className="pill pill-icon relative" title="Notifications and requests" aria-label={`Notifications, ${unread} unread`}
      aria-expanded={open} onClick={() => { setOpen(!open); void refresh().catch(() => {}); }}>
      <Bell size={16} />{(unread > 0 || pending.length > 0) && <span className="absolute top-0 right-0 w-2 h-2 rounded-full bg-[var(--accent)]" />}
    </button>
    {open && <div className="card absolute right-0 top-full mt-2 z-[90] w-[min(440px,90vw)] max-h-[80vh] overflow-y-auto p-4 flex flex-col gap-3 shadow-2xl" role="dialog" aria-label="Notifications">
      <div className="flex items-center justify-between"><h2 className="text-sm">Notifications</h2><button className="pill pill-icon" aria-label="Close notifications" onClick={() => setOpen(false)}><X size={14} /></button></div>
      {pending.map(request => <section key={request.id} className="rounded-xl border border-[var(--border-soft)] p-3 flex flex-col gap-2">
        <h3 className="text-xs font-medium">{request.kind === 'permission' ? 'Permission needed' : 'Your answer is needed'}</h3>
        <p className="text-xs">{request.details.summary || request.details.question}</p>
        {request.kind === 'permission' && <details className="text-xs"><summary className="cursor-pointer faint">Review action details</summary>
          <pre className="whitespace-pre-wrap break-all mt-2">{JSON.stringify(request.details.preview ?? {}, null, 2)}</pre></details>}
        {request.kind === 'question' ? <>
          {(request.details.options ?? []).map(option => <button className="pill text-left" key={option} disabled={!!submitting} onClick={() => void respond(request, option)}>{option}</button>)}
          <textarea className="input text-xs" rows={2} placeholder="Your answer" value={answers[request.id] ?? ''} onChange={e => setAnswers({ ...answers, [request.id]: e.target.value })} />
          <button className="pill self-end" disabled={!!submitting || !answers[request.id]?.trim()} onClick={() => void respond(request, answers[request.id])}>Reply and continue</button>
        </> : <div className="flex justify-end gap-2"><button className="pill" disabled={!!submitting} onClick={() => void respond(request, 'no')}>Deny</button>
          <button className="pill" disabled={!!submitting} onClick={() => void respond(request, 'yes')}>Allow this action</button></div>}
        <span className="text-[10px] faint">Task {request.run_id.slice(0, 8)} · waits for your explicit response</span>
      </section>)}
      {report?.runs.filter(r => r.status === 'interrupted' || r.status === 'failed').map(run => <details className="text-xs card p-3" key={run.id}>
        <summary className="cursor-pointer">{run.status === 'interrupted' ? 'Interrupted' : 'Failed'} Chisel task · {run.id.slice(0, 8)}</summary>
        {run.error && <p className="my-2" role="status">{run.error}</p>}
        <p className="faint my-2">Completed work is retained. Review it before starting a fresh task; old approvals cannot be reused. Resuming rechecks permissions and does not repeat completed steps.</p>
        <pre className="whitespace-pre-wrap break-all">{JSON.stringify(run.graph ?? {}, null, 2)}</pre>
        {run.status === 'interrupted' && <button className="pill mt-3" onClick={async () => { try { await apiPost('/api/agent/resume', { run_id: run.id }); navigate('chisel'); await refresh(); } catch (e) { setError(String(e)); } }}>Resume remaining work</button>}
      </details>)}
      <div className="flex items-center gap-2 text-[11px]">
        <select className="input !w-auto" aria-label="Notification filter" value={filter} onChange={e => setFilter(e.target.value)}>
          {['all', 'permission', 'question', 'completed', 'failed', 'background', 'download', 'update'].map(c => <option key={c}>{c}</option>)}
        </select><button onClick={async () => { await apiPost('/api/notifications/mark', { operation: 'read_all' }); await refresh(); }}>Read all</button>
        <button onClick={async () => { await apiPost('/api/notifications/mark', { operation: 'clear' }); await refresh(); }}>Clear history</button>
      </div>
      {report?.events.filter(e => filter === 'all' || e.category === filter).map(event => <div className="flex gap-2 border-t border-[var(--border-soft)] pt-3" key={event.id}>
        <button className="flex-1 min-w-0 text-left" onClick={() => void openEvent(event.id)}><span className={`text-xs ${event.read ? 'faint' : ''}`}>{event.title}</span>
          <p className="text-[11px] faint mt-1">{event.body}</p><span className="text-[10px] faint">{new Date(event.created * 1000).toLocaleString()} · {event.delivery}</span></button>
        <button aria-label="Dismiss notification" className="pill pill-icon self-start" onClick={async () => { await apiPost('/api/notifications/mark', { operation: 'dismiss', id: event.id }); await refresh(); }}><X size={12} /></button>
      </div>)}
      {!report?.events.length && !pending.length && <p className="text-xs faint py-5 text-center">You’re all caught up.</p>}
      {error && <p className="text-xs" role="alert">{error}</p>}
      {report?.storage_error && <p className="text-xs" role="alert">{report.storage_error}</p>}
    </div>}
  </div>;
}
