import { describe, expect, it } from 'vitest';

import { RoomFloor, TurnDetector, rms } from './listen';

/** Feed a pattern of levels, 50ms per frame, and report the states seen. */
function run(levels: number[], frameMs = 50) {
  const d = new TurnDetector();
  return levels.map((l) => d.push(l, frameMs));
}

const QUIET = 0.002;
const LOUD = 0.08;

describe('loudness', () => {
  it('is the mean, not the peak — one slam is not a sentence', () => {
    const slam = new Float32Array(100);
    slam[0] = 1;
    const speech = new Float32Array(100).fill(0.2);
    expect(rms(slam)).toBeLessThan(rms(speech));
  });
});

describe('the room floor', () => {
  it('rises slowly and falls quickly', () => {
    const floor = new RoomFloor(0.01);
    for (let i = 0; i < 5; i++) floor.observe(0.05, false);
    const afterRise = floor.value;
    for (let i = 0; i < 5; i++) floor.observe(0.001, false);
    expect(afterRise).toBeLessThan(0.05);          // did not leap up
    expect(floor.value).toBeLessThan(afterRise);   // came down faster
  });

  it('ignores frames while somebody is speaking', () => {
    // Otherwise a long sentence drags the floor up to meet itself and the
    // speaker becomes inaudible to the detector mid-word.
    const floor = new RoomFloor(0.005);
    for (let i = 0; i < 50; i++) floor.observe(0.5, true);
    expect(floor.value).toBe(0.005);
  });
});

describe('a turn', () => {
  it('waits while the room is quiet', () => {
    expect(run([QUIET, QUIET, QUIET]).every((s) => s === 'waiting')).toBe(true);
  });

  it('notices speech starting', () => {
    expect(run([QUIET, LOUD])[1]).toBe('speaking');
  });

  it('ends after enough silence, not at the first pause', () => {
    // 900ms hangover at 50ms a frame is 18 frames. A comma is not the end of
    // a sentence, and cutting someone off at one makes them repeat themselves.
    const states = run([QUIET, ...Array(10).fill(LOUD), ...Array(8).fill(QUIET)]);
    expect(states).not.toContain('finished');
    const longer = run([QUIET, ...Array(10).fill(LOUD), ...Array(20).fill(QUIET)]);
    expect(longer).toContain('finished');
  });

  it('refuses a clip too short to be a sentence', () => {
    // One loud frame is 50ms — a cough, a chair, a door.
    const states = run([QUIET, LOUD, ...Array(20).fill(QUIET)]);
    expect(states).toContain('tooShort');
    expect(states).not.toContain('finished');
  });

  it('stops eventually even if the room never goes quiet', () => {
    // A stuck microphone, or a television. Recording for ever is not an option.
    const states = run(Array(1400).fill(LOUD));
    expect(states).toContain('finished');
  });

  it('starts again cleanly', () => {
    const d = new TurnDetector();
    d.push(LOUD, 50);
    d.reset();
    expect(d.push(QUIET, 50)).toBe('waiting');
  });
});
