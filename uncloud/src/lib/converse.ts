/** Hands-free conversation: listen, answer, speak, listen again.
 *
 *  Kept out of the view because the awkward parts are lifecycle, not layout.
 *  A microphone opened and not closed keeps the recording light on after the
 *  window is gone, and an audio graph left running holds the device against
 *  every other application on the machine.
 *
 *  It does NOT listen while it is speaking. Without that the reply is heard as
 *  the next question and the thing talks to itself until stopped — the single
 *  most common way a voice loop embarrasses itself.
 */

import { TurnDetector, rms, type TurnState } from './listen';

export interface ConverseHandlers {
  /** A finished utterance, as recorded audio. Resolve with the reply text so
   *  it can be spoken; resolve with nothing to say nothing. */
  onUtterance: (audio: Blob) => Promise<void>;
  /** Live state, for showing what it is doing. */
  onState: (state: 'listening' | 'hearing' | 'thinking' | 'speaking' | 'off') => void;
  onError: (message: string) => void;
}

const FRAME = 2048;

export class Conversation {
  private stream: MediaStream | null = null;
  private context: AudioContext | null = null;
  private recorder: MediaRecorder | null = null;
  private chunks: Blob[] = [];
  private detector = new TurnDetector();
  private raf = 0;
  private running = false;
  //: Set while the reply is being spoken. Frames are still read — the loop
  //  has to keep running — but they are discarded rather than treated as the
  //  user talking, which is what stops it answering itself.
  private muted = false;

  private handlers: ConverseHandlers;

  constructor(handlers: ConverseHandlers) {
    this.handlers = handlers;
  }

  get active(): boolean {
    return this.running;
  }

  async start(): Promise<void> {
    if (this.running) return;
    try {
      this.stream = await navigator.mediaDevices.getUserMedia({
        audio: { echoCancellation: true, noiseSuppression: true },
      });
    } catch {
      this.handlers.onError(
        'Uncloud could not open the microphone. Allow access in System Settings '
        + '→ Privacy & Security → Microphone.');
      return;
    }

    this.running = true;
    this.context = new AudioContext();
    const source = this.context.createMediaStreamSource(this.stream);
    const analyser = this.context.createAnalyser();
    analyser.fftSize = FRAME;
    source.connect(analyser);

    const buffer = new Float32Array(analyser.fftSize);
    let last = performance.now();
    this.beginTurn();

    const tick = () => {
      if (!this.running) return;
      const now = performance.now();
      const elapsed = now - last;
      last = now;

      analyser.getFloatTimeDomainData(buffer);
      const state: TurnState = this.muted
        ? 'waiting'
        : this.detector.push(rms(buffer), elapsed);

      if (state === 'speaking') this.handlers.onState('hearing');
      if (state === 'finished') void this.finishTurn(true);
      if (state === 'tooShort') void this.finishTurn(false);

      this.raf = requestAnimationFrame(tick);
    };
    this.raf = requestAnimationFrame(tick);
  }

  private beginTurn(): void {
    if (!this.stream || !this.running) return;
    this.detector.reset();
    this.chunks = [];
    this.recorder = new MediaRecorder(this.stream);
    this.recorder.ondataavailable = (e) => {
      if (e.data.size) this.chunks.push(e.data);
    };
    this.recorder.start();
    this.handlers.onState('listening');
  }

  /** Close off the recording. `useIt` is false for a cough or a door. */
  private async finishTurn(useIt: boolean): Promise<void> {
    const recorder = this.recorder;
    if (!recorder || recorder.state === 'inactive') return;
    this.recorder = null;

    const audio = await new Promise<Blob>((resolve) => {
      recorder.onstop = () => resolve(new Blob(this.chunks, { type: 'audio/webm' }));
      recorder.stop();
    });

    if (!this.running) return;
    if (!useIt) { this.beginTurn(); return; }

    // Deaf while it answers, so its own voice is not the next question.
    this.muted = true;
    this.handlers.onState('thinking');
    try {
      await this.handlers.onUtterance(audio);
    } catch (e) {
      this.handlers.onError(e instanceof Error ? e.message : String(e));
    } finally {
      this.muted = false;
      if (this.running) this.beginTurn();
    }
  }

  /** Hold the microphone's output while the reply plays. */
  setSpeaking(speaking: boolean): void {
    this.muted = speaking;
    if (speaking) this.handlers.onState('speaking');
  }

  stop(): void {
    this.running = false;
    cancelAnimationFrame(this.raf);
    try { this.recorder?.state !== 'inactive' && this.recorder?.stop(); } catch { /* already stopped */ }
    this.recorder = null;
    // Every track, explicitly. Dropping the reference leaves the recording
    // indicator lit until the tab is closed.
    this.stream?.getTracks().forEach((t) => t.stop());
    this.stream = null;
    void this.context?.close().catch(() => {});
    this.context = null;
    this.handlers.onState('off');
  }
}
