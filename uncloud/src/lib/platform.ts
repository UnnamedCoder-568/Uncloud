/**
 * Where this interface is running: inside the desktop shell, or served to a
 * paired device over the local network.
 *
 * It is the same interface either way. What differs is what is reachable —
 * a browser cannot open a native folder picker, and a phone asking for a
 * folder on the computer it is paired with would be browsing someone else's
 * disk anyway — so the handful of places that care ask here.
 */

import { useSyncExternalStore } from 'react';

export function inDesktop(): boolean {
  return typeof window !== 'undefined' && '__TAURI_INTERNALS__' in window;
}

/** The chassis's breakpoint. Kept in step with `.split` and the drawer. */
const NARROW = '(max-width: 767.98px)';

function subscribe(onChange: () => void): () => void {
  const query = window.matchMedia(NARROW);
  query.addEventListener('change', onChange);
  return () => query.removeEventListener('change', onChange);
}

/** The same question, once, for an initial state. */
export function isNarrow(): boolean {
  return typeof window !== 'undefined' && window.matchMedia(NARROW).matches;
}

/** True on a phone-sized viewport. Re-renders when the answer changes. */
export function useNarrow(): boolean {
  return useSyncExternalStore(subscribe, () => window.matchMedia(NARROW).matches, () => false);
}

/** Send an unpaired browser to pairing. A no-op inside the desktop shell. */
export function goPair(): void {
  if (inDesktop() || window.location.pathname.startsWith('/pair')) return;
  window.location.assign('/pair');
}

/** Hand the browser a file to keep. The web equivalent of "Save a copy". */
export function downloadBlob(blob: Blob, name: string): void {
  const url = URL.createObjectURL(blob);
  const link = document.createElement('a');
  link.href = url;
  link.download = name;
  document.body.appendChild(link);
  link.click();
  link.remove();
  // Revoked later rather than immediately: Safari starts the download
  // asynchronously and a revoked URL gives it nothing to fetch.
  setTimeout(() => URL.revokeObjectURL(url), 30_000);
}
