/** Coming back to a page that was put away.
 *
 *  A phone browser does not keep a background tab running. Timers stop, open
 *  connections are dropped, and if memory is short the page is discarded and
 *  reloaded from scratch when you return to it. None of that reaches the
 *  engine — a render started from a phone keeps going and writes its file —
 *  but the page that was watching it comes back knowing nothing, with a
 *  progress bar frozen where it was and a picture it never collected.
 *
 *  So anything that polls has to be told when the page is awake again, rather
 *  than waiting for an interval that may not have run for ten minutes.
 *
 *  Four events, because no single one covers every browser: `visibilitychange`
 *  is the ordinary tab switch, `pageshow` fires when a page is restored from
 *  the back/forward cache (where timers were suspended wholesale), `focus`
 *  catches the window coming forward on desktop, and `online` catches the
 *  phone that woke on a different network than it slept on.
 */

export type Stop = () => void;

export function onWake(run: () => void): Stop {
  const wake = () => {
    if (typeof document !== 'undefined' && document.visibilityState === 'hidden') return;
    run();
  };
  document.addEventListener('visibilitychange', wake);
  window.addEventListener('pageshow', wake);
  window.addEventListener('focus', wake);
  window.addEventListener('online', wake);
  return () => {
    document.removeEventListener('visibilitychange', wake);
    window.removeEventListener('pageshow', wake);
    window.removeEventListener('focus', wake);
    window.removeEventListener('online', wake);
  };
}

/** Remember which jobs this view started, so a reload can pick them up again.
 *
 *  Only the ids: everything else about a job is the engine's to know, and
 *  asking it is also how we find out what happened while the page was away.
 */
export function remember(key: string, ids: string[]): void {
  try {
    if (ids.length) localStorage.setItem(key, JSON.stringify(ids));
    else localStorage.removeItem(key);
  } catch { /* private window, or storage refused — the loop still works */ }
}

export function remembered(key: string): string[] {
  try {
    const raw = JSON.parse(localStorage.getItem(key) || '[]');
    return Array.isArray(raw) ? raw.filter((id): id is string => typeof id === 'string') : [];
  } catch { return []; }
}
