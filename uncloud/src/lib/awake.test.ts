/** Coming back to a page a phone put away.
 *
 *  The failure this prevents: a render started from a phone, the browser sent
 *  to the background, and a page that comes back with a frozen progress bar and
 *  no picture — while the engine finished the work minutes ago.
 *
 *  The suite runs without a DOM, so the handful of browser objects this module
 *  touches are stubbed here rather than a headless browser being installed to
 *  hold four event listeners.
 */

import { beforeEach, describe, expect, it, vi } from 'vitest';

type Handler = () => void;

const listeners = new Map<string, Set<Handler>>();

function target() {
  return {
    addEventListener(event: string, fn: Handler) {
      const set = listeners.get(event) ?? new Set<Handler>();
      set.add(fn);
      listeners.set(event, set);
    },
    removeEventListener(event: string, fn: Handler) {
      listeners.get(event)?.delete(fn);
    },
  };
}

function fire(event: string) {
  for (const fn of [...(listeners.get(event) ?? [])]) fn();
}

const store = new Map<string, string>();

beforeEach(() => {
  listeners.clear();
  store.clear();
  (globalThis as Record<string, unknown>).document = { ...target(), visibilityState: 'visible' };
  (globalThis as Record<string, unknown>).window = target();
  (globalThis as Record<string, unknown>).localStorage = {
    getItem: (k: string) => store.get(k) ?? null,
    setItem: (k: string, v: string) => void store.set(k, v),
    removeItem: (k: string) => void store.delete(k),
  };
});

const { onWake, remember, remembered } = await import('./awake');

describe('onWake', () => {
  it('runs when the tab comes back', () => {
    const run = vi.fn();
    const stop = onWake(run);
    fire('visibilitychange');
    expect(run).toHaveBeenCalledTimes(1);
    stop();
  });

  it('runs when a suspended page is restored, and when the network returns', () => {
    const run = vi.fn();
    const stop = onWake(run);
    fire('pageshow');
    fire('online');
    expect(run).toHaveBeenCalledTimes(2);
    stop();
  });

  it('does nothing on the way out', () => {
    (globalThis as Record<string, unknown>).document = { ...target(), visibilityState: 'hidden' };
    const run = vi.fn();
    const stop = onWake(run);
    fire('visibilitychange');
    expect(run).not.toHaveBeenCalled();
    stop();
  });

  it('stops listening when told to', () => {
    const run = vi.fn();
    onWake(run)();
    fire('visibilitychange');
    fire('focus');
    expect(run).not.toHaveBeenCalled();
  });
});

describe('remembering jobs', () => {
  it('survives a reload', () => {
    remember('k', ['a', 'b']);
    expect(remembered('k')).toEqual(['a', 'b']);
  });

  it('forgets when there is nothing left', () => {
    remember('k', ['a']);
    remember('k', []);
    expect(remembered('k')).toEqual([]);
  });

  it('reads nonsense as nothing rather than throwing', () => {
    localStorage.setItem('k', '{not json');
    expect(remembered('k')).toEqual([]);
    localStorage.setItem('k', '{"id":"a"}');
    expect(remembered('k')).toEqual([]);
  });
});
