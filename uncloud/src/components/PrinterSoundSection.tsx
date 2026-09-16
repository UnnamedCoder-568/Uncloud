import { useState } from 'react';
import { printerSoundEnabled, setPrinterSoundEnabled } from '../lib/printer-sound';

export default function PrinterSoundSection() {
  const [enabled, setEnabled] = useState(printerSoundEnabled);

  function toggle() {
    const next = !enabled;
    setEnabled(next);
    setPrinterSoundEnabled(next);
  }

  return (
    <section className="card p-4">
      <div className="flex items-start justify-between gap-4">
        <div>
          <h2 className="text-sm mb-1">Old printer sound</h2>
          <p className="text-[11px] text-[var(--text-faint)] max-w-sm">
            Let Chat clatter like a dot-matrix printer while a visible reply is
            being written. Silent while the model loads, thinks, or searches.
          </p>
        </div>
        <button
          type="button"
          role="switch"
          aria-checked={enabled}
          aria-label="Old printer sound for Chat"
          onClick={toggle}
          className={`w-11 h-6 rounded-full shrink-0 transition relative ${enabled ? 'accent-bar' : 'bg-[var(--border)]'}`}
        >
          <span className={`absolute top-0.5 w-5 h-5 rounded-full bg-white transition ${enabled ? 'left-5' : 'left-0.5'}`} />
        </button>
      </div>
    </section>
  );
}
