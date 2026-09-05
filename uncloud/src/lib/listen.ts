/** Knowing when someone has finished speaking.
 *
 *  This is the whole difference between dictation and conversation. Dictation
 *  is a button held down; conversation is the machine noticing that you have
 *  stopped, without being told. Getting it wrong in either direction is worse
 *  than a button: cut somebody off mid-sentence and they repeat themselves,
 *  wait too long and they wonder whether it heard.
 *
 *  Measured as loudness over a short window, with a floor learned from the
 *  room rather than fixed. A fixed threshold works in one kitchen and fails in
 *  the next; a fan, a laptop, a street outside all sit at different levels.
 */

export interface ListenSettings {
  /** How much louder than the room counts as speech. */
  overRoom: number;
  /** Quiet for this long, and the turn is over. */
  hangoverMs: number;
  /** Never send a clip shorter than this — a cough is not a sentence. */
  minSpeechMs: number;
  /** Stop regardless after this, so a stuck microphone cannot record for ever. */
  maxMs: number;
}

export const DEFAULTS: ListenSettings = {
  overRoom: 2.2,
  hangoverMs: 900,
  minSpeechMs: 350,
  maxMs: 60_000,
};

/** Root-mean-square of a frame, which tracks perceived loudness far better
 *  than peak: one door slam should not read as a sentence. */
export function rms(frame: Float32Array): number {
  let sum = 0;
  for (let i = 0; i < frame.length; i++) sum += frame[i] * frame[i];
  return Math.sqrt(sum / frame.length);
}

/** A running estimate of the room's own noise.
 *
 *  Only quiet frames update it, and slowly, so a long sentence cannot drag the
 *  floor up to meet itself and make the speaker inaudible to the detector.
 */
export class RoomFloor {
  private level: number;

  constructor(initial = 0.005) {
    this.level = initial;
  }

  get value(): number {
    return this.level;
  }

  observe(level: number, speaking: boolean): void {
    if (speaking) return;
    // Rises slowly, falls quickly: a room that gets quieter should be
    // believed at once, a room that gets louder only after it persists.
    const rate = level > this.level ? 0.02 : 0.2;
    this.level = this.level + (level - this.level) * rate;
  }
}

export type TurnState = 'waiting' | 'speaking' | 'finished' | 'tooShort';

/** Tracks one turn: silence, then speech, then silence long enough to end it. */
export class TurnDetector {
  private floor = new RoomFloor();
  private speechMs = 0;
  private quietMs = 0;
  private started = false;
  private totalMs = 0;

  private settings: ListenSettings;

  constructor(settings: ListenSettings = DEFAULTS) {
    this.settings = settings;
  }

  /** Feed one frame. `frameMs` is how much time it represents. */
  push(level: number, frameMs: number): TurnState {
    this.totalMs += frameMs;
    const threshold = Math.max(this.floor.value * this.settings.overRoom, 0.004);
    const loud = level > threshold;
    this.floor.observe(level, loud);

    if (loud) {
      this.started = true;
      this.speechMs += frameMs;
      this.quietMs = 0;
    } else if (this.started) {
      this.quietMs += frameMs;
    }

    if (this.totalMs >= this.settings.maxMs) {
      return this.speechMs >= this.settings.minSpeechMs ? 'finished' : 'tooShort';
    }
    if (this.started && this.quietMs >= this.settings.hangoverMs) {
      return this.speechMs >= this.settings.minSpeechMs ? 'finished' : 'tooShort';
    }
    return this.started ? 'speaking' : 'waiting';
  }

  reset(): void {
    this.speechMs = 0;
    this.quietMs = 0;
    this.started = false;
    this.totalMs = 0;
  }
}
