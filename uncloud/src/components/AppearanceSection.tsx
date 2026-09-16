import { useState } from 'react';
import { applyAppearance, MONOCHROME, readAppearance } from '../lib/appearance';
import type { Appearance, ThemeChoice } from '../lib/appearance';

const PRESETS = ['#F2F2F2', '#60A5FA', '#A78BFA', '#34D399', '#F59E0B', '#FB7185'];

export default function AppearanceSection() {
  const [appearance, setAppearance] = useState<Appearance>(readAppearance);
  const update = (next: Appearance) => { setAppearance(next); applyAppearance(next); };

  return (
    <section className="card p-4">
      <h2 className="text-sm mb-1">Appearance</h2>
      <p className="text-[11px] text-[var(--text-faint)] mb-3">
        Monochrome by default. Add one accent if you want colour; generated media is never filtered.
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
    </section>
  );
}
