export type ThemeChoice = 'dark' | 'light' | 'system';
export interface Appearance { theme: ThemeChoice; accent: string }

export const MONOCHROME: Appearance = { theme: 'dark', accent: '#F2F2F2' };
const KEY = 'uncloud.appearance.v1';

function validHex(value: unknown): value is string {
  return typeof value === 'string' && /^#[0-9a-f]{6}$/i.test(value);
}

export function readAppearance(): Appearance {
  try {
    const stored = JSON.parse(localStorage.getItem(KEY) || '{}');
    const theme: ThemeChoice = ['dark', 'light', 'system'].includes(stored.theme)
      ? stored.theme : MONOCHROME.theme;
    return { theme, accent: validHex(stored.accent) ? stored.accent : MONOCHROME.accent };
  } catch { return MONOCHROME; }
}

function foreground(hex: string): string {
  const values = [1, 3, 5].map((at) => parseInt(hex.slice(at, at + 2), 16) / 255);
  const linear = values.map((v) => v <= 0.04045 ? v / 12.92 : ((v + 0.055) / 1.055) ** 2.4);
  const luminance = 0.2126 * linear[0] + 0.7152 * linear[1] + 0.0722 * linear[2];
  return luminance > 0.45 ? '#111111' : '#F7F7F7';
}

export function applyAppearance(value: Appearance, persist = true): void {
  const root = document.documentElement;
  const dark = value.theme === 'system'
    ? !window.matchMedia('(prefers-color-scheme: light)').matches
    : value.theme === 'dark';
  root.dataset.theme = dark ? 'dark' : 'light';
  root.style.setProperty('--accent', value.accent);
  root.style.setProperty('--accent-hover', `color-mix(in srgb, ${value.accent} 82%, ${dark ? 'white' : 'black'})`);
  root.style.setProperty('--accent-2', `color-mix(in srgb, ${value.accent} 58%, ${dark ? '#777' : '#aaa'})`);
  root.style.setProperty('--accent-on', foreground(value.accent));
  if (persist) {
    try { localStorage.setItem(KEY, JSON.stringify(value)); } catch { /* private browsing */ }
  }
}

export function initialiseAppearance(): void {
  applyAppearance(readAppearance(), false);
}
