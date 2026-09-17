import { useState } from 'react';
import { RotateCcw } from 'lucide-react';
import { applyAppearance, currentColour, MONOCHROME, PARTS, readAppearance } from '../lib/appearance';
import type { Appearance, PartId, ThemeChoice } from '../lib/appearance';

const PRESETS = ['#F2F2F2', '#60A5FA', '#A78BFA', '#34D399', '#F59E0B', '#FB7185'];

export default function AppearanceSection() {
  const [appearance, setAppearance] = useState<Appearance>(readAppearance);
  //: Colours are opened on request. Most people want the accent and nothing
  //  else, and six colour wells above that is a settings page shouting.
  const [painting, setPainting] = useState(false);
  const update = (next: Appearance) => { setAppearance(next); applyAppearance(next); };

  const repaint = (part: PartId, colour: string) =>
    update({ ...appearance, colours: { ...appearance.colours, [part]: colour } });

  const restore = (part: PartId) => {
    const colours = { ...appearance.colours };
    delete colours[part];
    update({ ...appearance, colours });
  };

  return (
    <section className="card p-4">
      <h2 className="text-sm mb-1">Appearance</h2>
      <p className="text-[11px] text-[var(--text-faint)] mb-3">
        Monochrome by default, so the only colour on screen is the work itself. Add an
        accent, or repaint every part of the interface — generated media is never filtered.
      </p>
      <div className="grid grid-cols-[1fr_auto] gap-3 items-end">
        <label className="field">
          <span className="label">Theme</span>
          <select className="input" value={appearance.theme}
                  onChange={(event) => update({ ...appearance, theme: event.target.value as ThemeChoice })}>
            <option value="dark">Dark</option>
            <option value="light">Light</option>
            <option value="system">Follow device</option>
          </select>
        </label>
        <label className="field">
          <span className="label">Custom accent</span>
          <input className="input w-16" type="color" value={appearance.accent}
                 onChange={(event) => update({ ...appearance, accent: event.target.value })} />
        </label>
      </div>
      <div className="flex items-center gap-2 mt-3 flex-wrap">
        {PRESETS.map((accent) => (
          <button key={accent} aria-label={`Use ${accent}`} title={accent}
                  onClick={() => update({ ...appearance, accent })}
                  className="w-7 h-7 rounded-full border border-[var(--border-strong)]"
                  style={{ background: accent, outline: appearance.accent.toLowerCase() === accent.toLowerCase()
                    ? '2px solid var(--text)' : 'none', outlineOffset: 2 }} />
        ))}
        <button className="pill ml-auto" onClick={() => update(MONOCHROME)}>Reset monochrome</button>
      </div>

      <div className="mt-4 pt-3 border-t border-[var(--border-soft)]">
        <button className="text-xs text-[var(--text-dim)] hover:text-[var(--text)] transition"
                onClick={() => setPainting((open) => !open)}>
          {painting ? 'Hide interface colours' : 'Change interface colours'}
        </button>
        {painting && (
          <div className="mt-3 flex flex-col gap-2">
            {PARTS.map((part) => (
              <div key={part.id} className="flex items-center gap-3">
                <input
                  type="color"
                  aria-label={part.name}
                  value={currentColour(part.id, appearance.colours[part.id])}
                  onChange={(event) => repaint(part.id, event.target.value)}
                  className="w-9 h-9 rounded-lg bg-transparent border border-[var(--border-strong)] shrink-0 cursor-pointer"
                />
                <span className="min-w-0 flex-1">
                  <span className="block text-xs">{part.name}</span>
                  <span className="block text-[10px] text-[var(--text-faint)]">{part.hint}</span>
                </span>
                {appearance.colours[part.id] && (
                  <button onClick={() => restore(part.id)} title={`Reset ${part.name.toLowerCase()}`}
                          className="p-1.5 rounded-lg text-[var(--text-faint)] hover:text-[var(--text)] transition">
                    <RotateCcw size={13} />
                  </button>
                )}
              </div>
            ))}
            <p className="text-[10px] text-[var(--text-faint)] leading-relaxed mt-1">
              Kept in this browser, so the computer and a paired phone can each look
              however suits the room they are in.
            </p>
          </div>
        )}
      </div>
    </section>
  );
}
