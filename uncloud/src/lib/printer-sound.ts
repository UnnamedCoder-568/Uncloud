const STORAGE_KEY = 'uncloud.chat.printerSound';
const VOLUME_KEY = 'uncloud.chat.printerVolume';
let volatilePreference: boolean | null = null;
let volatileVolume: number | null = null;

/** Loudest the printer is allowed to be, at the top of the slider.
 *
 *  Chosen against speech: this sits under a spoken reply rather than over it,
 *  and a printer that has to be turned down before anyone can hear the model
 *  is a printer nobody leaves on. */
const LOUDEST = 0.26;

/** How long a pause in the writing before the printer falls silent. Long
 *  enough to ride over the gap between two sentences, short enough that a step
 *  which stops to think is not narrated. */
const QUIET_AFTER = 900;

/** How loud, from 0 to 1. Its own setting rather than a property of the
 *  switch: the sound people want in a quiet room at midnight is not the one
 *  they want beside a fan, and neither is "off". */
export function printerVolume(): number {
  if (volatileVolume !== null) return volatileVolume;
  try {
    const stored = Number(localStorage.getItem(VOLUME_KEY));
    return Number.isFinite(stored) && stored > 0 ? clamp(stored) : 0.6;
  } catch {
    return 0.6;
  }
}

export function setPrinterVolume(level: number): void {
  const value = clamp(level);
  volatileVolume = value;
  try {
    localStorage.setItem(VOLUME_KEY, String(value));
    volatileVolume = null;
  } catch {
    // Storage refused. The slider still moves for this visit.
  }
  printerSound.refreshVolume();
}

function clamp(level: number): number {
  if (!Number.isFinite(level)) return 0.6;
  return Math.min(1, Math.max(0.05, level));
}

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

/** A small, procedural modern inkjet printer.
 *
 * No recording is shipped with the app. A soft roller bed, a low stepper hum
 * and short print-head passes make the familiar restrained desk-printer sound.
 * Keeping it procedural makes the feature tiny, offline, and safe to loop for
 * replies of any length.
 */
class PrinterSound {
  private context: AudioContext | null = null;
  private master: GainNode | null = null;
  private paper: AudioBufferSourceNode | null = null;
  private motor: OscillatorNode | null = null;
  private needleTimer: ReturnType<typeof setInterval> | null = null;
  private carriageTimer: ReturnType<typeof setInterval> | null = null;
  private quietTimer: ReturnType<typeof setTimeout> | null = null;
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
    master.gain.exponentialRampToValueAtTime(this.peak(), now + 0.035);
    master.connect(context.destination);
    this.master = master;

    // The smooth stepper motor beneath the paper feed.
    const motor = context.createOscillator();
    const motorGain = context.createGain();
    motor.type = 'triangle';
    motor.frequency.setValueAtTime(92, now);
    motorGain.gain.setValueAtTime(0.032, now);
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
    paperFilter.type = 'lowpass';
    paperFilter.frequency.setValueAtTime(520, now);
    paperFilter.Q.setValueAtTime(0.55, now);
    paperGain.gain.setValueAtTime(0.028, now);
    paper.connect(paperFilter).connect(paperGain).connect(master);
    paper.start(now);
    this.paper = paper;

    // Inkjet heads move in soft passes rather than the high, sharp strikes of
    // a dot-matrix printer.
    this.needleTimer = setInterval(() => this.strikeNeedles(), 240);
    this.carriageTimer = setInterval(() => this.carriageReturn(), 1450);
    this.strikeNeedles();
  }

  /** Text is arriving. Starts the printer if it is not already going, and
   *  keeps it going until the writing pauses.
   *
   *  For anything that writes in bursts rather than one continuous reply —
   *  Chisel prints a step, then runs a command that says nothing for ten
   *  seconds. A printer clattering through that silence is describing work
   *  that is not happening. */
  writing(): void {
    if (!printerSoundEnabled()) return;
    if (!this.running) this.start();
    if (this.quietTimer !== null) clearTimeout(this.quietTimer);
    this.quietTimer = setTimeout(() => {
      this.quietTimer = null;
      this.stop();
    }, QUIET_AFTER);
  }

  /** Apply a volume change to a printer that is already running. */
  refreshVolume(): void {
    const context = this.context;
    const master = this.master;
    if (!this.running || !context || !master) return;
    master.gain.cancelScheduledValues(context.currentTime);
    master.gain.setTargetAtTime(this.peak(), context.currentTime, 0.02);
  }

  private peak(): number {
    return Math.max(0.0001, LOUDEST * printerVolume());
  }

  stop(): void {
    if (this.needleTimer !== null) clearInterval(this.needleTimer);
    if (this.carriageTimer !== null) clearInterval(this.carriageTimer);
    if (this.quietTimer !== null) clearTimeout(this.quietTimer);
    this.needleTimer = null;
    this.carriageTimer = null;
    this.quietTimer = null;

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
    const count = 2;
    for (let i = 0; i < count; i++) {
      const at = now + i * 0.006;
      const needle = context.createOscillator();
      const gain = context.createGain();
      needle.type = 'triangle';
      needle.frequency.setValueAtTime(430 + Math.random() * 170, at);
      gain.gain.setValueAtTime(0.0001, at);
      gain.gain.exponentialRampToValueAtTime(0.055, at + 0.006);
      gain.gain.exponentialRampToValueAtTime(0.0001, at + 0.055);
      needle.connect(gain).connect(master);
      needle.start(at);
      needle.stop(at + 0.06);
    }
  }

  private carriageReturn(): void {
    const context = this.context;
    const master = this.master;
    if (!this.running || !context || !master) return;
    const now = context.currentTime;
    const carriage = context.createOscillator();
    const gain = context.createGain();
    carriage.type = 'triangle';
    carriage.frequency.setValueAtTime(155, now);
    carriage.frequency.exponentialRampToValueAtTime(72, now + 0.28);
    gain.gain.setValueAtTime(0.0001, now);
    gain.gain.exponentialRampToValueAtTime(0.07, now + 0.025);
    gain.gain.exponentialRampToValueAtTime(0.0001, now + 0.3);
    carriage.connect(gain).connect(master);
    carriage.start(now);
    carriage.stop(now + 0.31);
  }
}

export const printerSound = new PrinterSound();
