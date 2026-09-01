import { useState } from 'react';
import { open, save } from '@tauri-apps/plugin-dialog';
import { Check, FolderOpen, Loader2, Save, SaveAll, Trash2 } from 'lucide-react';
import { deleteOutput, getSettings, revealOutput, saveCopy } from '../lib/sidecar';

/**
 * Save / Save as / Reveal / Discard for one finished piece of generated work.
 *
 * Everything is written to the output folder as it is made, so the file always
 * already exists — Save and Save as are about getting a copy somewhere else.
 * Save asks for a folder and keeps the name; Save as asks for the name too.
 * Neither moves the original, so the Outputs gallery keeps showing the work.
 *
 * Discard is the other direction: a render nobody wants should not be left
 * cluttering the folder, so it deletes the auto-saved file too. That is not
 * recoverable — there is no trash here — so it asks once before doing it.
 */

// The output folder is the sensible starting point for both dialogs. Read fresh
// each time: it is a local call, and the folder is editable from Settings while
// this component stays mounted.
function defaultDir(): Promise<string> {
  return getSettings().then((s) => s.output_dir).catch(() => '');
}

export default function SaveActions({
  path,
  suggestedName,
  onDiscarded,
}: {
  path: string | null;
  /** Filename offered in the Save-as dialog. Defaults to the generated one. */
  suggestedName?: string;
  /** Clear the result from the view — the file behind it is gone. */
  onDiscarded?: () => void;
}) {
  const [busy, setBusy] = useState<'save' | 'saveAs' | 'discard' | null>(null);
  const [saved, setSaved] = useState<string | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [confirming, setConfirming] = useState(false);

  if (!path) return null;

  const name = suggestedName || path.split('/').pop() || 'image.png';

  async function run(which: 'save' | 'saveAs') {
    setBusy(which);
    setError(null);
    try {
      const start = await defaultDir();
      const dest =
        which === 'save'
          ? await open({ directory: true, multiple: false, defaultPath: start || undefined })
          : await save({ defaultPath: start ? `${start}/${name}` : name });
      // Dialog dismissed — not an error, just nothing to do.
      if (typeof dest !== 'string' || !dest) return;
      const result = await saveCopy(path!, dest, which === 'save');
      setSaved(result.path);
    } catch (e) {
      setError(String(e));
    } finally {
      setBusy(null);
    }
  }

  async function discard() {
    if (!confirming) {
      setConfirming(true);
      // Disarm on its own; a button left reading "Sure?" is a trap the next
      // time someone reaches for this row.
      setTimeout(() => setConfirming(false), 4000);
      return;
    }
    setBusy('discard');
    setError(null);
    try {
      await deleteOutput(path!);
      onDiscarded?.();
    } catch (e) {
      setError(String(e));
    } finally {
      setBusy(null);
      setConfirming(false);
    }
  }

  const button =
    'flex items-center gap-1.5 text-xs px-2.5 py-1.5 rounded-lg text-[var(--text-dim)] ' +
    'hover:text-white hover:bg-[var(--bg-raised)] transition disabled:opacity-40';

  return (
    <div className="flex flex-col items-center gap-1">
      <div className="flex items-center gap-1">
        <button className={button} onClick={() => run('save')} disabled={busy !== null}
                title="Copy to a folder, keeping the name">
          {busy === 'save' ? <Loader2 size={13} className="animate-spin" /> : <Save size={13} />}
          Save
        </button>
        <button className={button} onClick={() => run('saveAs')} disabled={busy !== null}
                title="Copy somewhere with a name of your choosing">
          {busy === 'saveAs' ? <Loader2 size={13} className="animate-spin" /> : <SaveAll size={13} />}
          Save as…
        </button>
        <button className={button} onClick={() => revealOutput(saved ?? path!)}
                title="Show the file in Finder">
          <FolderOpen size={13} /> Reveal
        </button>
        <button
          className={`${button} ${confirming ? 'text-rose-400' : 'hover:text-rose-400'}`}
          onClick={discard}
          disabled={busy !== null}
          title="Delete this render, including the auto-saved copy"
        >
          {busy === 'discard' ? <Loader2 size={13} className="animate-spin" /> : <Trash2 size={13} />}
          {confirming ? 'Delete for good?' : 'Discard'}
        </button>
      </div>
      {error ? (
        <span className="text-[11px] text-rose-400">{error}</span>
      ) : confirming ? (
        <span className="text-[11px] text-[var(--text-faint)]">
          This removes it from your output folder as well. Copies you saved elsewhere stay.
        </span>
      ) : saved ? (
        <span className="flex items-center gap-1 text-[11px] text-[var(--text-faint)]">
          <Check size={11} className="text-emerald-400" /> Copied to {saved}
        </span>
      ) : null}
    </div>
  );
}
