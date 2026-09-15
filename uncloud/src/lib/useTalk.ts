import { useCallback, useEffect, useRef, useState } from 'react';
import { Conversation } from './converse';
import { getLibrary, speakReply, transcribeAudio } from './sidecar';
import type { LocalModel } from './sidecar';

export type TalkState = 'off' | 'listening' | 'hearing' | 'thinking' | 'speaking';

/**
 * Talk to something and hear it answer: listen, transcribe, answer, speak,
 * listen again.
 *
 * `onHeard` receives what was said and resolves with what to say back, or
 * nothing to stay quiet. Everything it closes over is read through refs, so
 * the loop — built once, living across renders — always calls the CURRENT
 * handler and voice. A loop that captured its first render's state is how
 * Chat's conversation once listened perfectly and then did nothing with what
 * it heard, because the speech model had not loaded when the loop was made.
 */
export function useTalk(voice: string, onHeard: (said: string) => Promise<string | null | void>) {
  const [sttModel, setSttModel] = useState<LocalModel | null>(null);
  const [state, setState] = useState<TalkState>('off');
  const [error, setError] = useState<string | null>(null);
  const loop = useRef<Conversation | null>(null);
  const handler = useRef(onHeard);
  const voiceRef = useRef(voice);
  const sttRef = useRef<LocalModel | null>(null);
  const player = useRef<HTMLAudioElement | null>(null);

  useEffect(() => { handler.current = onHeard; });
  useEffect(() => { voiceRef.current = voice; }, [voice]);
  useEffect(() => { sttRef.current = sttModel; }, [sttModel]);

  useEffect(() => {
    getLibrary()
      .then((ms) => setSttModel(ms.find((m) => m.category === 'voice-stt' && m.ready) ?? null))
      .catch(() => setSttModel(null));
  }, []);

  /** Say something, and wait until it has been said. Deaf meanwhile. */
  const speak = useCallback(async (text: string) => {
    if (!text.trim()) return;
    const url = await speakReply(text.trim(), voiceRef.current);
    const audio = player.current ?? new Audio();
    player.current = audio;
    audio.src = url;
    loop.current?.setSpeaking(true);
    try {
      await audio.play();
      await new Promise<void>((resolve) => {
        audio.onended = () => resolve();
        audio.onerror = () => resolve();
        audio.onpause = () => resolve();
      });
    } finally {
      loop.current?.setSpeaking(false);
      URL.revokeObjectURL(url);
    }
  }, []);

  const stop = useCallback(() => {
    loop.current?.stop();
    loop.current = null;
    player.current?.pause();
    setState('off');
  }, []);

  const start = useCallback(async () => {
    if (loop.current?.active) return;
    setError(null);
    const conversation = new Conversation({
      onState: setState,
      onError: (message) => { setError(message); stop(); },
      onUtterance: async (audio) => {
        const model = sttRef.current;
        if (!model) {
          setError('No speech-to-text model is installed. Add Whisper from Models.');
          return;
        }
        const said = await transcribeAudio(model.path, audio, 'turn.webm');
        if (!said.trim()) return;
        const reply = await handler.current(said.trim());
        if (reply && reply.trim()) await speak(reply);
      },
    });
    loop.current = conversation;
    await conversation.start();
  }, [speak, stop]);

  // The microphone must not outlive the view.
  useEffect(() => () => {
    loop.current?.stop();
    loop.current = null;
    player.current?.pause();
  }, []);

  return {
    sttModel,
    state,
    error,
    active: state !== 'off',
    start,
    stop,
    toggle: () => (loop.current?.active ? stop() : void start()),
    speak,
  };
}

/** What the loop is doing, in words. */
export function describeTalk(state: TalkState): string {
  return {
    off: 'Not listening',
    listening: 'Listening…',
    hearing: 'Hearing you…',
    thinking: 'Thinking…',
    speaking: 'Speaking…',
  }[state];
}
