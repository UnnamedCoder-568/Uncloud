import { useEffect, useRef, useState } from 'react';
import { printerSound, printerSoundEnabled, printerVolume,
         setPrinterSoundEnabled, setPrinterVolume } from '../lib/printer-sound';

export default function PrinterSoundSection() {
  const [enabled, setEnabled] = useState(printerSoundEnabled);
  const [volume, setVolume] = useState(printerVolume);
  //: A sample, so the slider can be set without sending a message to hear it.
  const [trying, setTrying] = useState(false);
  const sample = useRef<ReturnType<typeof setTimeout> | null>(null);

  // A printer left running by a settings page nobody is on any more.
  useEffect(() => () => {
    if (sample.current !== null) clearTimeout(sample.current);
    printerSound.stop();
  }, []);

  function toggle() {
    const next = !enabled;
    setEnabled(next);
    setPrinterSoundEnabled(next);
    if (!next) setTrying(false);
  }

  function change(level: number) {
    setVolume(level);
    setPrinterVolume(level);   // heard immediately when the sample is playing
  }

  function tryIt() {
    if (sample.current !== null) clearTimeout(sample.current);
    if (trying) {
      printerSound.stop();
      setTrying(false);
      return;
    }
    setTrying(true);
    printerSound.start();
    sample.current = setTimeout(() => {
      printerSound.stop();
      setTrying(false);
      sample.current = null;
    }, 2500);
  }

  return (
    <section className="card p-4">
      <div className="flex items-start justify-between gap-4">
        <div>
          <h2 className="text-sm mb-1">Old printer sound</h2>
          <p className="text-[11px] text-[var(--text-faint)] max-w-sm">
            Clatter like a dot-matrix printer while a model is actually writing —
            in Chat and in Chisel. Silent while it loads, thinks, or searches.
          </p>
        </div>
        <button
          type="button"
          role="switch"
          aria-checked={enabled}
          aria-label="Old printer sound"
          onClick={toggle}
          className={`w-11 h-6 rounded-full shrink-0 transition relative ${enabled ? 'accent-bar' : 'bg-[var(--border)]'}`}
        >
          <span className={`absolute top-0.5 w-5 h-5 rounded-full bg-white transition ${enabled ? 'left-5' : 'left-0.5'}`} />
        </button>
      </div>

      {enabled && (
        <div className="mt-4 flex items-center gap-3">
          <span className="label shrink-0">Volume</span>
          <input
            type="range"
            aria-label="Printer volume"
            min={5}
            max={100}
            value={Math.round(volume * 100)}
            onChange={(event) => change(Number(event.target.value) / 100)}
            className="flex-1 accent-[var(--accent)]"
          />
          <span className="text-[11px] text-[var(--text-faint)] w-9 text-right tabular-nums">
            {Math.round(volume * 100)}%
          </span>
          <button type="button" onClick={tryIt} className="pill shrink-0">
            {trying ? 'Stop' : 'Try it'}
          </button>
        </div>
      )}
    </section>
  );
}
