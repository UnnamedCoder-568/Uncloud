import { useEffect, useState } from 'react';
import { invoke } from '@tauri-apps/api/core';
import { apiPost } from '../lib/sidecar';
import { inDesktop } from '../lib/platform';
import { getNotifications } from './NotificationCenter';
import type { NotificationPreferences } from './NotificationCenter';

export default function NotificationsSettings() {
  const [preferences, setPreferences] = useState<NotificationPreferences | null>(null);
  const [background, setBackground] = useState(false);
  const [error, setError] = useState('');
  const [permission, setPermission] = useState('');
  const [requesting, setRequesting] = useState(false);
  useEffect(() => { getNotifications().then(r => setPreferences(r.preferences)).catch(e => setError(String(e)));
    if (inDesktop()) void invoke<{ background: boolean }>('desktop_preferences').then(p => setBackground(p.background)).catch(() => {});
  }, []);
  useEffect(() => { if (inDesktop()) void invoke<string>('notification_permission', { request: false })
    .then(setPermission).catch(e => setPermission(String(e))); }, []);
  const save = async (values: Partial<NotificationPreferences>) => {
    try { setPreferences(await apiPost<NotificationPreferences>('/api/notifications/preferences', { values })); setError(''); }
    catch (e) { setError(String(e)); }
  };
  return <section className="card p-5 sm:p-6 flex flex-col gap-4">
    <h2 className="text-sm">Notifications</h2><p className="text-xs faint max-w-xl">Private previews and native system alerts. Focus, Do Not Disturb and OS notification settings still apply. The bell keeps requests available even if an alert is suppressed.</p>
    {inDesktop() && <div className="flex flex-wrap gap-2 text-xs"><button className="pill" disabled={requesting} onClick={async () => {
      setRequesting(true); try { setPermission(await invoke<string>('notification_permission', { request: true })); }
      catch (e) { setError(String(e)); } finally { setRequesting(false); }
    }}>Enable system alerts</button><button className="pill" onClick={async () => {
      try { await apiPost('/api/notifications/test', {}); setError(''); } catch (e) { setError(String(e)); }
    }}>Send test alert</button><span className="w-full faint">{permission}</span></div>}
    {preferences && <>
      {([['enabled', 'Enable notifications'], ['sound', 'Notification sounds'], ['system_sound', 'Use the system sound'], ['background', 'Allow background notifications'], ['quiet', 'Quiet mode · silent notifications']] as const).map(([key, label]) =>
        <label className="flex items-center gap-3 text-xs" key={key}><input type="checkbox" checked={preferences[key]} disabled={!inDesktop()} onChange={e => void save({ [key]: e.target.checked })} />{label}</label>)}
      <div className="grid grid-cols-2 gap-3 border-t border-[var(--border-soft)] pt-4">{Object.entries(preferences.categories).map(([category, enabled]) => <label className="text-xs flex gap-3" key={category}>
        <input type="checkbox" disabled={!inDesktop()} checked={enabled} onChange={e => void save({ categories: { ...preferences.categories, [category]: e.target.checked } })} />
        {({ permission: 'Permission requests', question: 'Model questions', completed: 'Task completed', failed: 'Task failed', background: 'Background updates', download: 'Model downloads', update: 'App updates' } as Record<string, string>)[category]}</label>)}</div>
    </>}
    <div className="border-t border-[var(--border-soft)] pt-4"><label className="text-xs flex gap-3"><input type="checkbox" disabled={!inDesktop()} checked={background} onChange={async e => { const enabled = e.target.checked;
      try { await invoke('set_background_running', { enabled }); setBackground(enabled); } catch (e) { setError(String(e)); } }} />Keep running in background</label>
      <p className="text-[11px] faint mt-2">When enabled, closing the window hides it and tasks keep running. Use the tray/menu bar to reopen, stop tasks or quit. Otherwise closing quits Uncloud.</p></div>
    {error && <p role="alert" className="text-xs">{error}</p>}
  </section>;
}
