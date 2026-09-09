/** The agreements, before the application is used.
 *
 *  Shown on a first launch and again when a document changes materially.
 *
 *  Uncloud is the application where the separation matters most, so the screen
 *  says it rather than implying it: the thing on the other side of this wall is
 *  an agent that can write files and run shell commands, and agreeing to a
 *  document gives it none of that. Permissions are asked for separately, at the
 *  moment they are needed, and this screen never speaks for them.
 *
 *  The text is on the screen rather than behind a link — somebody who has to
 *  open a browser to read what they are agreeing to will not read it — and the
 *  version sent back is the version displayed, so a consent record can never
 *  describe a page nobody saw.
 */

import { useCallback, useEffect, useState } from 'react';
import { Check, FileText } from 'lucide-react';

import Markdown from '../components/Markdown';
import Wordmark from '../components/Wordmark';
import { acceptTerms, getLegalDocument, getLegalState,
         type LegalDocument, type LegalState } from '../lib/sidecar';

export default function TermsView({ onSettled }: { onSettled: () => void }) {
  const [state, setState] = useState<LegalState | null>(null);
  const [document, setDocument] = useState<LegalDocument | null>(null);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);

  const load = useCallback(() => {
    getLegalState()
      .then((next) => {
        setState(next);
        if (next.settled) { onSettled(); return; }
        const first = next.outstanding[0];
        if (first) getLegalDocument(first.id).then(setDocument).catch(() => undefined);
      })
      .catch(() => setError('Could not reach the Uncloud engine.'));
  }, [onSettled]);

  useEffect(load, [load]);

  async function agree() {
    if (!document) return;
    setBusy(true);
    setError(null);
    try {
      // The version displayed, not whatever the engine holds now. A mismatch
      // is refused rather than silently recorded against the newer one.
      await acceptTerms(document.id, document.version);
      setDocument(null);
      load();
    } catch {
      setError('That version is no longer current. Restart to see what changed.');
    } finally {
      setBusy(false);
    }
  }

  if (!state || !document) {
    return (
      <div className="h-screen w-screen flex items-center justify-center dot-ground">
        <span className="glow"><Wordmark size={40} spinning /></span>
      </div>
    );
  }

  const remaining = state.outstanding.length;
  const changed =
    state.outstanding.find((o) => o.id === document.id)?.because === 'changed';

  return (
    <div className="h-screen w-screen flex items-center justify-center p-8 overflow-hidden">
      <div className="card w-full max-w-3xl flex flex-col gap-5 p-6 min-h-0">
        <div className="flex items-center justify-between gap-4 flex-wrap">
          <div className="flex items-center gap-2">
            <FileText size={18} className="text-[var(--text-dim)]" />
            <h2 className="text-lg font-medium">{document.title}</h2>
          </div>
          <div className="flex items-center gap-2 text-xs text-[var(--text-dim)] font-mono">
            <span>v{document.version}</span>
            {remaining > 1 && <span>· {remaining} to read</span>}
          </div>
        </div>

        {changed && (
          <p className="text-sm text-[var(--text-dim)] border-l-2 border-[var(--accent)] pl-3">
            {document.changes
              || 'This has changed materially since you agreed to it, so your '
                 + 'earlier agreement does not carry over.'}
          </p>
        )}

        <div className="overflow-y-auto min-h-0 max-h-[52vh] pr-3">
          <Markdown>{document.body ?? ""}</Markdown>
        </div>

        {error && <p className="text-sm text-[var(--danger,#f87171)]">{error}</p>}

        <div className="flex items-center justify-between gap-4 flex-wrap border-t
                        border-[var(--border)] pt-4">
          <p className="text-xs text-[var(--text-faint)] max-w-[44ch] leading-relaxed">
            Agreeing here gives Uncloud no permission to do anything on this computer.
            Reading files, writing them and running commands are asked for separately,
            when they happen.
          </p>
          <button className="grad-button text-base flex items-center gap-2"
                  disabled={busy} onClick={agree}>
            <Check size={15} /> I agree
          </button>
        </div>
      </div>
    </div>
  );
}
