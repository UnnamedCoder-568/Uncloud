import { useCallback, useEffect, useRef, useState } from 'react';
import { Conversation } from './converse';
import { getLibrary, speakReply, transcribeAudio } from './sidecar';
import { endNativeTurn, nativeListening, startNativeListener } from './nativeListen';
import type { LocalModel } from './sidecar';

export type TalkState = 'off' | 'listening' | 'hearing' | 'thinking' | 'speaking';

/**
 * Talk to something and hear it answer: listen, transcribe, answer, speak,
 * listen again.
 *
 * Two ways of listening, and the difference is most of what makes this feel
 * quick. Natively — Apple's on-device recogniser, transcribing while you speak
 * — the words are already there when you stop. Through the browser, nothing
 * starts until you have finished: a clip is recorded, uploaded, and a model
 * loads to read it, which is a second or more of silence every single turn.
 * The native path is used wherever it exists; the other is the fallback and
 * the only path off macOS.
 *
 * `onHeard` receives what was said, and a `say` function. Calling `say` with
 * each sentence as the model writes it is what stops a person waiting for a
 * whole paragraph to be composed and synthesised before they hear anything;
 * the queue plays them in order and keeps the microphone deaf meanwhile.
 *
 * Everything it closes over is read through refs, so the loop — built once,
 * living across renders — always calls the CURRENT handler and voice. A loop
 * that captured its first render's state is how Chat's conversation once
 * listened perfectly and did nothing with what it heard.
 */
export function useTalk(
  voice: string,
  onHeard: (said: string, say: (text: string) => void) => Promise<string | null | void>,
) {
  const [sttModel, setSttModel] = useState<LocalModel | null>(null);
  const [native, setNative] = useState(false);
  const [state, setState] = useState<TalkState>('off');
  const [error, setError] = useState<string | null>(null);
  /** What the recogniser has heard so far this turn, for showing live. */
  const [heard, setHeard] = useState('');

  const loop = useRef<Conversation | null>(null);
  const stopNative = useRef<(() => void) | null>(null);
  const handler = useRef(onHeard);
  const voiceRef = useRef(voice);
  const sttRef = useRef<LocalModel | null>(null);
  const player = useRef<HTMLAudioElement | null>(null);
  /** Replies are spoken one after another, in the order they were asked for. */
  const queue = useRef<Promise<void>>(Promise.resolve());
  const speakingCount = useRef(0);
  const running = useRef(false);

  useEffect(() => { handler.current = onHeard; });
  useEffect(() => { voiceRef.current = voice; }, [voice]);
  useEffect(() => { sttRef.current = sttModel; }, [sttModel]);

  useEffect(() => {
    void nativeListening().then(setNative);
    getLibrary()
      .then((ms) => setSttModel(ms.find((m) => m.category === 'voice-stt' && m.ready) ?? null))
      .catch(() => setSttModel(null));
  }, []);

  /** Deaf while it talks, or the reply becomes the next question. */
  const muted = useCallback((quiet: boolean) => {
    loop.current?.setSpeaking(quiet);
    setState(quiet ? 'speaking' : 'listening');
  }, []);

  const play = useCallback(async (text: string) => {
    const url = await speakReply(text.trim(), voiceRef.current);
    const audio = player.current ?? new Audio();
    player.current = audio;
    audio.src = url;
    try {
      await audio.play();
      await new Promise<void>((resolve) => {
        audio.onended = () => resolve();
        audio.onerror = () => resolve();
        audio.onpause = () => resolve();
      });
    } finally {
      URL.revokeObjectURL(url);
    }
  }, []);

  /** Queue something to be said. Returns immediately: the caller is usually
   *  mid-stream and must not be blocked by the speaking. */
  const say = useCallback((text: string) => {
    if (!text.trim()) return;
    speakingCount.current += 1;
    muted(true);
    queue.current = queue.current
      .then(() => play(text))
      .catch((e) => setError(e instanceof Error ? e.message : String(e)))
      .finally(() => {
        speakingCount.current -= 1;
        if (speakingCount.current === 0 && running.current) muted(false);
      });
  }, [muted, play]);

  const stop = useCallback(() => {
    running.current = false;
    loop.current?.stop();
    loop.current = null;
    stopNative.current?.();
    stopNative.current = null;
    player.current?.pause();
    setState('off');
    setHeard('');
  }, []);

  /** One turn: hand the words to the caller, and speak whatever comes back
   *  that it did not already say itself. */
  const answer = useCallback(async (said: string) => {
    if (!said.trim()) return;
    setState('thinking');
    setHeard('');
    try {
      const reply = await handler.current(said.trim(), say);
      if (reply && reply.trim()) say(reply);
    } catch (e) {
      setError(e instanceof Error ? e.message : String(e));
    } finally {
      if (speakingCount.current === 0 && running.current) setState('listening');
    }
  }, [say]);

  const start = useCallback(async () => {
    if (running.current) return;
    setError(null);
    running.current = true;

    if (await nativeListening()) {
      try {
        stopNative.current = await startNativeListener((event) => {
          switch (event.event) {
            case 'ready':
              setState('listening');
              break;
            case 'partial':
            case 'final':
              // Only while listening: the recogniser keeps reporting during a
              // reply, and showing that would look like it heard itself.
              if (speakingCount.current === 0) {
                setHeard(event.text ?? '');
                if ((event.text ?? '').trim()) setState('hearing');
              }
              break;
            case 'endOfTurn':
              if (speakingCount.current === 0) void answer(event.text ?? '');
              break;
            case 'error':
              setError(event.message ?? 'The listener stopped.');
              stop();
              break;
            case 'ended':
              if (running.current) stop();
              break;
            default:
              break;
          }
        });
        return;
      } catch (e) {
        // Fall through to the browser path rather than leaving someone with
        // no way to talk at all.
        setError(e instanceof Error ? e.message : String(e));
        stopNative.current = null;
      }
    }

    const conversation = new Conversation({
      onState: (s) => setState(s),
      onError: (message) => { setError(message); stop(); },
      onUtterance: async (audio) => {
        const model = sttRef.current;
        if (!model) {
          setError('No speech-to-text model is installed. Add Whisper from Models.');
          return;
        }
        const said = await transcribeAudio(model.path, audio, 'turn.webm');
        await answer(said);
      },
    });
    loop.current = conversation;
    await conversation.start();
  }, [answer, stop]);

  // The microphone must not outlive the view.
  useEffect(() => () => {
    running.current = false;
    loop.current?.stop();
    loop.current = null;
    stopNative.current?.();
    player.current?.pause();
  }, []);

  return {
    sttModel,
    /** True when listening natively — no speech model needed, and quicker. */
    native,
    state,
    error,
    heard,
    active: state !== 'off',
    /** Whether talking is possible at all: natively, or with a speech model. */
    ready: native || !!sttModel,
    start,
    stop,
    toggle: () => (state !== 'off' ? stop() : void start()),
    /** End this turn now rather than waiting for a pause. */
    endTurn: () => (native ? endNativeTurn() : Promise.resolve()),
    say,
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

/** Split a stream of reply text into sentences as they complete.
 *
 *  Speaking a sentence at a time is what removes most of the wait: the first
 *  words are heard while the model is still writing the rest. Anything short
 *  is held back — a fragment spoken alone sounds like a mistake.
 */
/** Shorter than this is a breath, not a sentence, and is held back. */
const MIN_SPOKEN = 12;

export class Sentences {
  private held = '';

  /** Sentences that are now complete. */
  push(chunk: string): string[] {
    this.held += chunk;
    const out: string[] = [];
    //: Where to look for the next ending. A boundary rejected as too short is
    //  not reconsidered — the sentence simply grows past it — which is what
    //  keeps "Yes." from being spoken as a sentence of its own.
    let from = 0;
    for (;;) {
      const match = /[.!?…](?=\s|$)|\n\n/.exec(this.held.slice(from));
      if (!match) break;
      const end = from + match.index + match[0].length;
      const sentence = this.held.slice(0, end).trim();
      if (sentence.length < MIN_SPOKEN) {
        // Wait for more, unless there is already more to join it to.
        if (end >= this.held.trimEnd().length) break;
        from = end;
        continue;
      }
      out.push(sentence);
      this.held = this.held.slice(end).trimStart();
      from = 0;
    }
    return out;
  }

  /** Whatever is left when the reply ends. */
  rest(): string {
    const last = this.held.trim();
    this.held = '';
    return last;
  }
}
