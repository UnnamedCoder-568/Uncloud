const STORAGE_KEY = 'uncloud.chat.printerSound';
let volatilePreference: boolean | null = null;

export function printerSoundEnabled(): boolean {
  try {
    const stored = localStorage.getItem(STORAGE_KEY);
    return stored === null ? (volatilePreference ?? false) : stored === 'on';
  } catch {
    return volatilePreference ?? false;
  }
}

export function setPrinterSoundEnabled(enabled: boolean): void {
  volatilePreference = enabled;
  try {
    localStorage.setItem(STORAGE_KEY, enabled ? 'on' : 'off');
    volatilePreference = null;
  } catch {
    // Private browsing or a locked-down webview can refuse storage. The
    // switch still works for the current visit; it simply cannot be kept.
  }
  if (enabled) printerSound.prepare();
  else printerSound.stop();
}

type AudioContextConstructor = new () => AudioContext;

/** A small, procedural dot-matrix printer.
 *
 * No recording is shipped with the app. A filtered noise bed makes the paper
 * feed, short square-wave taps make the print head, and an occasional sweep
 * suggests a carriage return. Keeping it procedural makes the feature tiny,
 * offline, and safe to loop for replies of any length.
 */
class PrinterSound {
  private context: AudioContext | null = null;
  private master: GainNode | null = null;
  private paper: AudioBufferSourceNode | null = null;
  private motor: OscillatorNode | null = null;
  private needleTimer: ReturnType<typeof setInterval> | null = null;
  private carriageTimer: ReturnType<typeof setInterval> | null = null;
  private running = false;

  /** Called from the Send gesture so browser audio policies can be satisfied
   * before model loading and the first token introduce asynchronous gaps. */
  prepare(): void {
    if (!printerSoundEnabled() || typeof window === 'undefined') return;
    if (!this.context) {
      const extended = window as typeof window & {
        webkitAudioContext?: AudioContextConstructor;
      };
      const Context = window.AudioContext || extended.webkitAudioContext;
      if (!Context) return;
      this.context = new Context();
    }
    if (this.context.state === 'suspended') {
      void this.context.resume().catch(() => undefined);
    }
  }

  start(): void {
    if (this.running || !printerSoundEnabled()) return;
    this.prepare();
    const context = this.context;
    if (!context) return;

    this.running = true;
    const now = context.currentTime;
    const master = context.createGain();
    master.gain.setValueAtTime(0.0001, now);
    master.gain.exponentialRampToValueAtTime(0.16, now + 0.035);
    master.connect(context.destination);
    this.master = master;

    // The low mechanical hum beneath the print head.
    const motor = context.createOscillator();
    const motorGain = context.createGain();
    motor.type = 'sawtooth';
    motor.frequency.setValueAtTime(58, now);
    motorGain.gain.setValueAtTime(0.025, now);
    motor.connect(motorGain).connect(master);
    motor.start(now);
    this.motor = motor;

    // Filtered noise is the paper and rollers rather than a harsh hiss.
    const buffer = context.createBuffer(1, context.sampleRate * 2, context.sampleRate);
    const samples = buffer.getChannelData(0);
    for (let i = 0; i < samples.length; i++) samples[i] = Math.random() * 2 - 1;
    const paper = context.createBufferSource();
    const paperFilter = context.createBiquadFilter();
    const paperGain = context.createGain();
    paper.buffer = buffer;
    paper.loop = true;
    paperFilter.type = 'bandpass';
    paperFilter.frequency.setValueAtTime(760, now);
    paperFilter.Q.setValueAtTime(0.7, now);
    paperGain.gain.setValueAtTime(0.018, now);
    paper.connect(paperFilter).connect(paperGain).connect(master);
    paper.start(now);
    this.paper = paper;

    // A slightly imperfect rhythm sounds mechanical; perfect metronomic taps
    // sound like a broken smoke alarm, which is a different Settings feature.
    this.needleTimer = setInterval(() => this.strikeNeedles(), 54);
    this.carriageTimer = setInterval(() => this.carriageReturn(), 1850);
    this.strikeNeedles();
  }

  stop(): void {
    if (this.needleTimer !== null) clearInterval(this.needleTimer);
    if (this.carriageTimer !== null) clearInterval(this.carriageTimer);
    this.needleTimer = null;
    this.carriageTimer = null;

    const context = this.context;
    const master = this.master;
    const paper = this.paper;
    const motor = this.motor;
    this.master = null;
    this.paper = null;
    this.motor = null;
    this.running = false;
    if (!context || !master) return;

    const now = context.currentTime;
    master.gain.cancelScheduledValues(now);
    master.gain.setValueAtTime(Math.max(master.gain.value, 0.0001), now);
    master.gain.exponentialRampToValueAtTime(0.0001, now + 0.045);
    try { paper?.stop(now + 0.06); } catch { /* already stopped */ }
    try { motor?.stop(now + 0.06); } catch { /* already stopped */ }
    setTimeout(() => master.disconnect(), 90);
  }

  private strikeNeedles(): void {
    const context = this.context;
    const master = this.master;
    if (!this.running || !context || !master) return;
    const now = context.currentTime;
    const count = Math.random() > 0.72 ? 3 : 2;
    for (let i = 0; i < count; i++) {
      const at = now + i * 0.006;
      const needle = context.createOscillator();
      const gain = context.createGain();
      needle.type = 'square';
      needle.frequency.setValueAtTime(1650 + Math.random() * 1050, at);
      gain.gain.setValueAtTime(0.0001, at);
      gain.gain.exponentialRampToValueAtTime(0.11, at + 0.0015);
      gain.gain.exponentialRampToValueAtTime(0.0001, at + 0.012);
      needle.connect(gain).connect(master);
      needle.start(at);
      needle.stop(at + 0.014);
    }
  }

  private carriageReturn(): void {
    const context = this.context;
    const master = this.master;
    if (!this.running || !context || !master) return;
    const now = context.currentTime;
    const carriage = context.createOscillator();
    const gain = context.createGain();
    carriage.type = 'sawtooth';
    carriage.frequency.setValueAtTime(380, now);
    carriage.frequency.exponentialRampToValueAtTime(95, now + 0.18);
    gain.gain.setValueAtTime(0.0001, now);
    gain.gain.exponentialRampToValueAtTime(0.055, now + 0.012);
    gain.gain.exponentialRampToValueAtTime(0.0001, now + 0.2);
    carriage.connect(gain).connect(master);
    carriage.start(now);
    carriage.stop(now + 0.21);
  }
}

export const printerSound = new PrinterSound();
