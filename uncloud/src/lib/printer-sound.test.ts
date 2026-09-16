import { afterEach, describe, expect, it, vi } from 'vitest';
import { printerSoundEnabled, setPrinterSoundEnabled } from './printer-sound';

function fakeStorage(initial?: string) {
  const values = new Map<string, string>();
  if (initial !== undefined) values.set('uncloud.chat.printerSound', initial);
  return {
    getItem: (key: string) => values.get(key) ?? null,
    setItem: (key: string, value: string) => { values.set(key, value); },
  };
}

afterEach(() => vi.unstubAllGlobals());

describe('old printer sound preference', () => {
  it('is opt-in', () => {
    vi.stubGlobal('localStorage', fakeStorage());
    expect(printerSoundEnabled()).toBe(false);
  });

  it('persists both switch positions', () => {
    vi.stubGlobal('localStorage', fakeStorage());
    setPrinterSoundEnabled(true);
    expect(printerSoundEnabled()).toBe(true);
    setPrinterSoundEnabled(false);
    expect(printerSoundEnabled()).toBe(false);
  });

  it('fails silent when preferences are unavailable', () => {
    vi.stubGlobal('localStorage', {
      getItem: () => { throw new Error('blocked'); },
      setItem: () => { throw new Error('blocked'); },
    });
    expect(printerSoundEnabled()).toBe(false);
    expect(() => setPrinterSoundEnabled(true)).not.toThrow();
    expect(printerSoundEnabled()).toBe(true);
  });
});
