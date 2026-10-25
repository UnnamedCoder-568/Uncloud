import { createContext, useCallback, useContext, useEffect, useRef, useState } from 'react';
import type { ReactNode } from 'react';
import { api, apiPost } from './sidecar';

export interface UserEvent { id: string; category: string; title: string; body: string; target: string;
  run_id: string; request_id: string; conversation_id: string; created: number; read: boolean; delivery: string; }
export interface Interaction { id: string; run_id: string; kind: 'permission' | 'question'; status: string;
  expires: number; details: { category?: string; summary?: string; preview?: Record<string, unknown>;
    question?: string; options?: string[] }; }
interface AgentRun { id: string; status: string; graph?: Record<string, unknown>; updated: number; error?: string }
export interface NotificationPreferences { enabled: boolean; sound: boolean; system_sound: boolean;
  background: boolean; quiet: boolean; categories: Record<string, boolean>; }
export interface NotificationReport { events: UserEvent[]; requests: Interaction[]; runs: AgentRun[];
  storage_error?: string; preferences: NotificationPreferences; }
export const getNotifications = () => api<NotificationReport>('/api/notifications');

interface InteractionsState {
  report: NotificationReport | null;
  submitting: string | null;
  error: string;
  refresh: () => Promise<void>;
  respond: (request: Interaction, answer: string) => Promise<void>;
}
const Context = createContext<InteractionsState | null>(null);

export function InteractionProvider({ children }: { children: ReactNode }) {
  const [report, setReport] = useState<NotificationReport | null>(null);
  const [submitting, setSubmitting] = useState<string | null>(null);
  const [error, setError] = useState('');
  const answering = useRef<string | null>(null);
  const revision = useRef(0);
  const refresh = useCallback(async () => {
    const version = ++revision.current;
    const value = await getNotifications();
    if (version !== revision.current) return;
    setReport(value);
    window.dispatchEvent(new CustomEvent('uncloud.agent-progress', { detail: value.runs }));
  }, []);
  useEffect(() => {
    const update = () => { void refresh().catch(() => {}); };
    update();
    const timer = setInterval(() => { if (document.visibilityState !== 'hidden') update(); }, 4000);
    window.addEventListener('focus', update);
    window.addEventListener('uncloud.interaction', update);
    return () => {
      revision.current++;
      clearInterval(timer);
      window.removeEventListener('focus', update);
      window.removeEventListener('uncloud.interaction', update);
    };
  }, [refresh]);

  const respond = useCallback(async (request: Interaction, answer: string) => {
    // One authenticated decision across the inline card and notification drawer.
    // The engine remains responsible for checking ownership, expiry and policy.
    if (answering.current) return;
    answering.current = request.id;
    setSubmitting(request.id); setError('');
    try {
      await apiPost(`/api/interactions/${request.id}/answer`, { answer });
      revision.current++;
      setReport(value => value && { ...value, requests: value.requests.filter(r => r.id !== request.id) });
      await refresh().catch(() => {});
    } catch (e) {
      setError(e instanceof Error ? e.message : String(e));
      await refresh().catch(() => {});
    } finally {
      answering.current = null;
      setSubmitting(null);
    }
  }, [refresh]);
  return <Context value={{ report, submitting, error, refresh, respond }}>{children}</Context>;
}

export function useInteractions() {
  const value = useContext(Context);
  if (!value) throw new Error('InteractionProvider is required');
  return value;
}
