/** Leaving the application for the web.
 *
 *  Inside the desktop shell a link has nowhere to go on its own: the webview
 *  receives a request for a new window, has no handler for it, and drops it.
 *  So every link the application showed — in a reply, in release notes, on the
 *  model catalogue — did nothing when pressed. They are routed to the system
 *  browser here instead. Served to a paired phone, the browser already does
 *  the right thing and is left to do it.
 *
 *  Web pages only. A model's reply is untrusted text and can contain any link
 *  it likes; `file:`, `javascript:` and custom schemes are refused here as well
 *  as in the shell's capability, so neither check is the only one.
 */

import { inDesktop } from './platform';

export function isWebLink(url: string): boolean {
  try {
    const { protocol } = new URL(url);
    return protocol === 'https:' || protocol === 'http:';
  } catch {
    return false;
  }
}

/** Open a page in the person's own browser. Returns false if it was refused. */
export async function openExternal(url: string): Promise<boolean> {
  if (!isWebLink(url)) return false;
  if (inDesktop()) {
    const { openUrl } = await import('@tauri-apps/plugin-opener');
    await openUrl(url);
    return true;
  }
  window.open(url, '_blank', 'noopener,noreferrer');
  return true;
}

/** Send every outbound link in the document to the browser.
 *
 *  Installed once, in the desktop shell only. Catching clicks here rather than
 *  giving every anchor its own handler is what fixes the links already in the
 *  application — including ones inside rendered replies, which no component
 *  wrote and none could remember to handle.
 */
export function interceptExternalLinks(): () => void {
  if (!inDesktop()) return () => {};
  const onClick = (event: MouseEvent) => {
    if (event.defaultPrevented || event.button !== 0) return;
    const anchor = (event.target as Element | null)?.closest?.('a[href]') as HTMLAnchorElement | null;
    if (!anchor) return;
    const href = anchor.href;
    const outbound = anchor.target === '_blank'
      || (isWebLink(href) && new URL(href).origin !== window.location.origin);
    if (!outbound) return;
    event.preventDefault();
    void openExternal(href);
  };
  document.addEventListener('click', onClick, true);
  return () => document.removeEventListener('click', onClick, true);
}
