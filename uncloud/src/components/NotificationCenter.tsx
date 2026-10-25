import { useCallback, useEffect, useState } from 'react';
import { Bell, X } from 'lucide-react';
import { listen } from '@tauri-apps/api/event';
import { invoke } from '@tauri-apps/api/core';
import { apiPost } from '../lib/sidecar';
import { inDesktop } from '../lib/platform';
import { useDismiss } from '../lib/useDismiss';
import type { View } from './Sidebar';
import { resolveView } from '../lib/workspaces';
import { getNotifications, useInteractions } from '../lib/interactions';
import { InteractionCard } from './PendingInteractions';
export { getNotifications } from '../lib/interactions';
export type { UserEvent, NotificationReport, NotificationPreferences } from '../lib/interactions';

export default function NotificationCenter({ navigate }: { navigate: (view: View) => void }) {
  const { report, refresh, error: interactionError } = useInteractions();
  const [open, setOpen] = useState(false);
  const [filter, setFilter] = useState('all');
  const [error, setError] = useState('');
  const ref = useDismiss(open, () => setOpen(false));
  const openEvent = useCallback(async (id: string) => {
    // Resolve the native ID against authenticated history. The event cannot
    // supply an arbitrary URL, permission answer or command to execute.
    const history = await getNotifications();
    const event = history.events.find(e => e.id === id);
    if (!event) return;
    const destination = resolveView(event.target);
    if (!destination) return;
    navigate(destination);
    if (event.conversation_id) window.dispatchEvent(new CustomEvent('uncloud.open-conversation', { detail: event.conversation_id }));
    setOpen(!event.request_id && event.target === 'chisel');
    await apiPost('/api/notifications/mark', { operation: 'read', id });
    await refresh();
  }, [navigate, refresh]);
  useEffect(() => {
    let unlisten: (() => void) | undefined;
    let alive = true;
    if (inDesktop()) {
      void listen<string>('notification-open', e => { void openEvent(e.payload).catch(() => {}); }).then(off => { if (alive) unlisten = off; else off(); });
      void invoke<{ last_click?: string }>('desktop_preferences', { consume: true }).then(p => { if (p.last_click) void openEvent(p.last_click); }).catch(() => {});
    }
    return () => { alive = false; unlisten?.(); };
  }, [refresh, openEvent]);

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
      {pending.map(request => <InteractionCard key={request.id} request={request} />)}
      {report?.runs.filter(r => r.status === 'interrupted' || r.status === 'failed').map(run => <details className="text-xs card p-3" key={run.id}>
        <summary className="cursor-pointer">{run.status === 'interrupted' ? 'Interrupted' : 'Failed'} Chisel task · {run.id.slice(0, 8)}</summary>
        {run.error && <p className="my-2" role="status">{run.error}</p>}
        <p className="faint my-2">Completed work is retained. Review it before starting a fresh task; old approvals cannot be reused. Resuming rechecks permissions and does not repeat completed steps.</p>
        <pre className="whitespace-pre-wrap break-all">{JSON.stringify(run.graph ?? {}, null, 2)}</pre>
        {(run.status === 'interrupted' || run.status === 'failed'
          && run.graph?.halt_reason === 'Approval request expired without an answer') &&
          <button className="pill mt-3" onClick={async () => { try { await apiPost('/api/agent/resume', { run_id: run.id }); navigate('chisel'); await refresh(); } catch (e) { setError(String(e)); } }}>Resume remaining work</button>}
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
      {interactionError && <p className="text-xs" role="alert">{interactionError}</p>}
      {report?.storage_error && <p className="text-xs" role="alert">{report.storage_error}</p>}
    </div>}
  </div>;
}
