import { useCallback, useEffect, useState } from 'react';
import { getSettings } from './sidecar';
import type { Settings } from './sidecar';

/**
 * Settings that stay current.
 *
 * Views in Uncloud mount once and stay mounted, so anything read in a
 * `useEffect(..., [])` is a snapshot of whenever the app started. Settings are
 * edited on a different screen, which meant a toggle could be on in Settings
 * and still read as off everywhere else — Chisel kept warning that it was
 * sandboxed after full device access had been granted.
 *
 * Re-reads when the window regains focus, which covers switching to Settings
 * and back, and on a slow timer for anything changed by the engine itself. It
 * is a local call over loopback, so the cost is negligible.
 */
export function useSettings(pollMs = 5000): Settings | null {
  const [settings, setSettings] = useState<Settings | null>(null);

  const read = useCallback(() => {
    getSettings().then(setSettings).catch(() => undefined);
  }, []);

  useEffect(() => {
    read();
    const onFocus = () => read();
    window.addEventListener('focus', onFocus);
    document.addEventListener('visibilitychange', onFocus);
    const t = setInterval(read, pollMs);
    return () => {
      window.removeEventListener('focus', onFocus);
      document.removeEventListener('visibilitychange', onFocus);
      clearInterval(t);
    };
  }, [read, pollMs]);

  return settings;
}
