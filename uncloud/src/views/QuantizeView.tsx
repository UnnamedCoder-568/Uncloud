/**
 * Quantize: make a version of a model that fits this Mac.
 *
 * This existed for weeks as a card wedged into the middle of a four-hundred
 * line Models page, under a heading that never says the word "quantise" — and
 * it returned NOTHING at all when there was no model it could work on. So the
 * commonest way to meet the feature was an empty space where it would have
 * been, which is indistinguishable from it not existing.
 *
 * It gets its own screen for the same reason Training has one: it is a slow,
 * deliberate operation on a model that a person decides to run, not a control
 * that belongs beside a download button. And the empty state says what is
 * missing rather than rendering nothing, because "there is nothing here yet"
 * and "this feature is absent" have to look different.
 */

import { useCallback, useEffect, useState } from 'react';
import { Gauge, Boxes, AlertTriangle } from 'lucide-react';
import Quantize, { quantisable } from '../components/Quantize';
import { getLibrary } from '../lib/sidecar';
import type { LocalModel } from '../lib/sidecar';
import { useLibraryVersion } from '../lib/library-changed';

export default function QuantizeView() {
  const libraryVersion = useLibraryVersion();
  const [library, setLibrary] = useState<LocalModel[] | null>(null);
  const [error, setError] = useState<string | null>(null);

  const refresh = useCallback(async () => {
    try {
      setLibrary(await getLibrary());
      setError(null);
    } catch (e) {
      setError(String(e));
    }
  }, []);

  useEffect(() => { refresh(); }, [refresh, libraryVersion]);

  const candidates = library ? quantisable(library) : [];

  return (
    <div className="h-full overflow-y-auto">
      <div className="max-w-3xl mx-auto px-6 py-8">
        <div className="flex items-start gap-3 mb-2">
          <div className="w-9 h-9 rounded-xl bg-[var(--bg-inset)] flex items-center justify-center shrink-0">
            <Gauge size={17} className="text-[var(--text-dim)]" />
          </div>
          <div>
            <h1 className="text-2xl font-semibold leading-tight">Quantize</h1>
            <p className="text-[13px] text-[var(--text-dim)] mt-1 max-w-xl leading-relaxed">
              Build a smaller copy of an image model once, so it loads in
              seconds and stays in memory instead of being rebuilt for every
              prompt.
            </p>
          </div>
        </div>

        {error && (
          <div className="card p-3 mt-6 flex items-start gap-2.5 text-[12px]">
            <AlertTriangle size={14} className="text-[var(--text-faint)] mt-0.5 shrink-0" />
            <span className="text-[var(--text-dim)]">
              Could not read the model library: {error}
            </span>
          </div>
        )}

        {library === null && !error && (
          <p className="text-[12px] text-[var(--text-faint)] mt-8">
            Reading the model library&hellip;
          </p>
        )}

        {library !== null && candidates.length === 0 && (
          /* Said out loud, rather than an empty page. Rendering nothing here
             is what made the feature look like it had been removed. */
          <div className="card p-5 mt-8">
            <div className="flex items-start gap-3">
              <div className="w-8 h-8 rounded-lg bg-[var(--bg-inset)] flex items-center justify-center shrink-0">
                <Boxes size={15} className="text-[var(--text-faint)]" />
              </div>
              <div className="min-w-0">
                <h2 className="text-sm mb-1.5">Nothing here can be quantised yet</h2>
                <p className="text-[11.5px] text-[var(--text-faint)] leading-relaxed max-w-xl">
                  This works on full-precision image models over a gigabyte —
                  the kind you download as a checkpoint. Anything already built
                  for mflux is quantised by definition and is left alone, and
                  text, video and audio models do not go through this at all.
                </p>
                <p className="text-[11.5px] text-[var(--text-faint)] leading-relaxed max-w-xl mt-2">
                  Install an image model from <strong>Models</strong> and it
                  will appear here.
                </p>
              </div>
            </div>
          </div>
        )}

        {candidates.length > 0 && (
          <div className="mt-7">
            <Quantize models={library ?? []} onBuilt={refresh} />
          </div>
        )}
      </div>
    </div>
  );
}
