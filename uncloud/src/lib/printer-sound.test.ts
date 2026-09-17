import { afterEach, describe, expect, it, vi } from 'vitest';
import { printerSoundEnabled, printerVolume, setPrinterSoundEnabled,
         setPrinterVolume } from './printer-sound';

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

  it('starts at a volume somebody can hear, and remembers a new one', () => {
    vi.stubGlobal('localStorage', fakeStorage());
    expect(printerVolume()).toBe(0.6);
    setPrinterVolume(0.25);
    expect(printerVolume()).toBe(0.25);
  });

  it('never goes to silent-but-on, or past the top of the slider', () => {
    vi.stubGlobal('localStorage', fakeStorage());
    // Off is the switch's job. A volume of zero would be a printer that is
    // enabled, does its work, and cannot be heard — indistinguishable from
    // the feature being broken.
    setPrinterVolume(0);
    expect(printerVolume()).toBe(0.05);
    setPrinterVolume(4);
    expect(printerVolume()).toBe(1);
    setPrinterVolume(Number.NaN);
    expect(printerVolume()).toBe(0.6);
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
