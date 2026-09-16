/** Listening through the app rather than through the browser.
 *
 *  The browser's recorder can only hand over a finished clip, so every turn
 *  pays for an upload and a transcription after the person has stopped
 *  talking. The native listener transcribes as the words arrive — on the
 *  device, with Apple's own recogniser — so the text is ready the moment
 *  there is a silence to act on.
 *
 *  macOS only. `nativeListening()` is what decides, and everything here is
 *  skipped where the answer is no: the Whisper path still works, and is the
 *  only path on Windows and Linux.
 */

import { invoke } from '@tauri-apps/api/core';
import { listen } from '@tauri-apps/api/event';
import { inDesktop } from './platform';

export interface ListenerEvent {
  /** ready · partial · final · endOfTurn · error · ended */
  event: string;
  text?: string;
  message?: string;
}

/** Whether this build can listen natively. Cached: it cannot change while the
 *  app is running, and it is asked on every render of the voice controls. */
let known: Promise<boolean> | null = null;
export function nativeListening(): Promise<boolean> {
  if (!inDesktop()) return Promise.resolve(false);
  known = known ?? invoke<boolean>('listener_available').catch(() => false);
  return known;
}

/** Start listening. Returns a stop function; call it when the turn ends or the
 *  view goes away, because a microphone nobody closed keeps the recording
 *  light on. */
export async function startNativeListener(
  onEvent: (event: ListenerEvent) => void,
  locale?: string,
): Promise<() => void> {
  const unlisten = await listen<ListenerEvent>('listener', (message) => onEvent(message.payload));
  try {
    await invoke('listener_start', { locale: locale ?? null });
  } catch (error) {
    unlisten();
    throw error;
  }
  let stopped = false;
  return () => {
    if (stopped) return;
    stopped = true;
    unlisten();
    void invoke('listener_stop').catch(() => {});
  };
}

/** End this turn now, without waiting for a pause — the button a person
 *  presses when they have finished and do not want to wait to be noticed. */
export function endNativeTurn(): Promise<void> {
  return invoke<void>('listener_end_turn').catch(() => undefined);
}
