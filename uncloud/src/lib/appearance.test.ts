/** Repainting the interface, and putting it back.
 *
 *  The failure worth guarding: a colour cleared in Settings that stays on the
 *  screen, because an inline override on the root element outlives the setting
 *  that wrote it. Reset then looks broken, which is worse than never offering
 *  the choice.
 */

import { beforeEach, describe, expect, it } from 'vitest';

const properties = new Map<string, string>();
const store = new Map<string, string>();

beforeEach(() => {
  properties.clear();
  store.clear();
  (globalThis as Record<string, unknown>).document = {
    documentElement: {
      dataset: {} as Record<string, string>,
      style: {
        setProperty: (k: string, v: string) => void properties.set(k, v),
        removeProperty: (k: string) => void properties.delete(k),
      },
    },
  };
  (globalThis as Record<string, unknown>).window = {
    matchMedia: () => ({ matches: false }),
    getComputedStyle: () => ({ getPropertyValue: () => '' }),
  };
  (globalThis as Record<string, unknown>).getComputedStyle = () => ({ getPropertyValue: () => '' });
  (globalThis as Record<string, unknown>).localStorage = {
    getItem: (k: string) => store.get(k) ?? null,
    setItem: (k: string, v: string) => void store.set(k, v),
    removeItem: (k: string) => void store.delete(k),
  };
});

const { applyAppearance, foreground, MONOCHROME, readAppearance } = await import('./appearance');

describe('appearance', () => {
  it('is monochrome until someone says otherwise', () => {
    expect(readAppearance()).toEqual(MONOCHROME);
    applyAppearance(MONOCHROME);
    expect(properties.get('--accent')).toBe('#F2F2F2');
    expect(properties.has('--bg')).toBe(false);
  });

  it('paints a chosen colour, and what depends on it', () => {
    applyAppearance({ ...MONOCHROME, colours: { surface: '#203040' } });
    expect(properties.get('--surface')).toBe('#203040');
    expect(properties.get('--surface-hover')).toContain('#203040');
    expect(properties.get('--surface-sunken')).toContain('#203040');
  });

  it('removes a colour that was cleared rather than leaving it on screen', () => {
    applyAppearance({ ...MONOCHROME, colours: { bg: '#123456', surface: '#203040' } });
    applyAppearance({ ...MONOCHROME, colours: { surface: '#203040' } });
    expect(properties.has('--bg')).toBe(false);
    expect(properties.get('--surface')).toBe('#203040');
  });

  it('survives a reload', () => {
    applyAppearance({ theme: 'light', accent: '#60A5FA', colours: { text: '#111111' } });
    expect(readAppearance()).toEqual({ theme: 'light', accent: '#60A5FA', colours: { text: '#111111' } });
  });

  it('ignores stored nonsense rather than painting with it', () => {
    localStorage.setItem('uncloud.appearance.v1',
      JSON.stringify({ theme: 'neon', accent: 'red', colours: { bg: 'drop table' } }));
    expect(readAppearance()).toEqual(MONOCHROME);
  });

  it('keeps text readable on whatever the accent is', () => {
    expect(foreground('#FFFFFF')).toBe('#111111');
    expect(foreground('#101010')).toBe('#F7F7F7');
  });
});
