/** How the application looks, and how much of that a person may change.
 *
 *  Monochrome is the default and the opinion: the interface is grey so that
 *  the work — a picture, a video, a page of writing — is the only colour on
 *  the screen. But it is an opinion, not a constraint. One accent covers most
 *  people; anyone who wants the whole surface in their own colours can set
 *  every part of it, and reset to the default in one press.
 *
 *  Everything is stored in this browser and applied as CSS variables on the
 *  root element. The engine is not told, and does not care: this is how the
 *  application looks on THIS screen, and a phone paired over the network keeps
 *  its own answer.
 */

export type ThemeChoice = 'dark' | 'light' | 'system';

/** The parts of the surface a person can repaint, in the order they are shown.
 *
 *  Each maps onto a chassis token. They are deliberately few: these seven
 *  cover every surface in the application, and a list of forty would be a
 *  stylesheet with a colour picker in front of it. */
export const PARTS = [
  { id: 'bg', token: '--bg', name: 'Background', hint: 'Behind everything' },
  { id: 'sidebar', token: '--sidebar', name: 'Sidebar', hint: 'The rail down the left' },
  { id: 'surface', token: '--surface', name: 'Panels', hint: 'Cards, menus, inputs' },
  { id: 'border', token: '--border', name: 'Lines', hint: 'Dividers and outlines' },
  { id: 'text', token: '--text', name: 'Text', hint: 'What you read' },
  { id: 'text-2', token: '--text-2', name: 'Quiet text', hint: 'Labels and captions' },
] as const;

export type PartId = (typeof PARTS)[number]['id'];

export interface Appearance {
  theme: ThemeChoice;
  accent: string;
  /** Only what the person actually changed. An empty object is the default
   *  palette, which is what makes "reset" a delete rather than a guess at
   *  what the theme used to be. */
  colours: Partial<Record<PartId, string>>;
}

export const MONOCHROME: Appearance = { theme: 'dark', accent: '#F2F2F2', colours: {} };
const KEY = 'uncloud.appearance.v1';

function validHex(value: unknown): value is string {
  return typeof value === 'string' && /^#[0-9a-f]{6}$/i.test(value);
}

export function readAppearance(): Appearance {
  try {
    const stored = JSON.parse(localStorage.getItem(KEY) || '{}');
    const theme: ThemeChoice = ['dark', 'light', 'system'].includes(stored.theme)
      ? stored.theme : MONOCHROME.theme;
    const colours: Partial<Record<PartId, string>> = {};
    for (const part of PARTS) {
      const chosen = stored.colours?.[part.id];
      if (validHex(chosen)) colours[part.id] = chosen;
    }
    return {
      theme,
      accent: validHex(stored.accent) ? stored.accent : MONOCHROME.accent,
      colours,
    };
  } catch { return MONOCHROME; }
}

/** Black or white, whichever can be read on this colour. */
export function foreground(hex: string): string {
  const values = [1, 3, 5].map((at) => parseInt(hex.slice(at, at + 2), 16) / 255);
  const linear = values.map((v) => v <= 0.04045 ? v / 12.92 : ((v + 0.055) / 1.055) ** 2.4);
  const luminance = 0.2126 * linear[0] + 0.7152 * linear[1] + 0.0722 * linear[2];
  return luminance > 0.45 ? '#111111' : '#F7F7F7';
}

/** The tokens each part drives, beyond its own.
 *
 *  A surface colour on its own leaves the hover state and the sunken variant
 *  behind, which is how a repainted panel ends up with the old grey showing
 *  through the moment the pointer arrives. Each is mixed from the chosen
 *  colour rather than picked separately: six decisions, not twenty.
 */
function derived(part: PartId, hex: string, dark: boolean): [string, string][] {
  const lift = dark ? 'white' : 'black';
  const sink = dark ? 'black' : 'white';
  switch (part) {
    case 'surface':
      return [
        ['--surface-hover', `color-mix(in srgb, ${hex} 88%, ${lift})`],
        ['--surface-sunken', `color-mix(in srgb, ${hex} 88%, ${sink})`],
      ];
    case 'sidebar':
      return [
        ['--rail-hover', `color-mix(in srgb, ${hex} 92%, ${lift})`],
        ['--rail-active', `color-mix(in srgb, ${hex} 82%, ${lift})`],
      ];
    case 'border':
      return [['--border-strong', `color-mix(in srgb, ${hex} 70%, ${lift})`]];
    case 'text':
      return [['--text-3', `color-mix(in srgb, ${hex} 62%, ${sink})`]];
    default:
      return [];
  }
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

  // Cleared first, so removing a colour actually removes it: an override left
  // on the root element outlives the setting that put it there, and the reset
  // button would then appear to do nothing.
  for (const part of PARTS) {
    root.style.removeProperty(part.token);
    for (const [token] of derived(part.id, '#000000', dark)) root.style.removeProperty(token);
  }
  for (const part of PARTS) {
    const chosen = value.colours[part.id];
    if (!chosen) continue;
    root.style.setProperty(part.token, chosen);
    for (const [token, colour] of derived(part.id, chosen, dark)) {
      root.style.setProperty(token, colour);
    }
  }

  if (persist) {
    try { localStorage.setItem(KEY, JSON.stringify(value)); } catch { /* private browsing */ }
  }
}

export function initialiseAppearance(): void {
  applyAppearance(readAppearance(), false);
}

/** What a part looks like right now, for a colour input that has to show
 *  something: the person's choice, or whatever the theme is using. */
export function currentColour(part: PartId, chosen?: string): string {
  if (chosen) return chosen;
  if (typeof window === 'undefined') return '#000000';
  const token = PARTS.find((p) => p.id === part)!.token;
  const value = getComputedStyle(document.documentElement).getPropertyValue(token).trim();
  return /^#[0-9a-f]{6}$/i.test(value) ? value : '#000000';
}
