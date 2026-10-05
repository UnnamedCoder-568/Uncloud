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

  const load = useCallback(async () => {
    setError(null);
    try {
      const next = await getLegalState();
      setState(next);
      if (next.settled) { onSettled(); return; }
      const first = next.outstanding[0];
      if (!first) throw new Error('No agreement available');
      setDocument(await getLegalDocument(first.id));
    } catch {
      setError('We could not load the agreements. Check that Uncloud is running, then try again.');
    }
  }, [onSettled]);

  useEffect(() => { void load(); }, [load]);

  async function agree() {
    if (!document) return;
    setBusy(true);
    setError(null);
    try {
      // The version displayed, not whatever the engine holds now. A mismatch
      // is refused rather than silently recorded against the newer one.
      await acceptTerms(document.id, document.version);
      setDocument(null);
      await load();
    } catch {
      setError('We could not save your choice. Try again; if this document has changed, restart Uncloud to review the current version.');
    } finally {
      setBusy(false);
    }
  }

  if (!state || !document) {
    return (
      <div className="h-screen w-screen flex items-center justify-center p-6">
        <div className="flex flex-col items-center gap-5 max-w-sm text-center" role="status">
          <Wordmark size={36} spinning={!error} />
          <p className="text-sm text-[var(--text-dim)]">{error || 'Preparing your agreements…'}</p>
          {error && <button className="px-4 py-2 rounded-xl bg-[var(--bg-raised)] text-sm" onClick={() => { void load(); }}>Try again</button>}
        </div>
      </div>
    );
  }

  const remaining = state.outstanding.length;
  const changed =
    state.outstanding.find((o) => o.id === document.id)?.because === 'changed';

  return (
    <div className="h-screen w-screen flex items-center justify-center p-4 sm:p-8 overflow-hidden">
      <div className="card w-full max-w-3xl flex flex-col gap-6 p-5 sm:p-8 min-h-0 max-h-[calc(100vh-3rem)]">
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

        {error && <p role="alert" className="text-sm text-[var(--text-dim)]">{error}</p>}

        <div className="flex items-center justify-between gap-4 flex-wrap border-t
                        border-[var(--border)] pt-4">
          <p className="text-xs text-[var(--text-faint)] max-w-[44ch] leading-relaxed">
            Agreeing here gives Uncloud no permission to do anything on this computer.
            Reading files, writing them and running commands are asked for separately,
            when they happen.
          </p>
          <button className="px-5 py-2.5 rounded-xl bg-[var(--text)] text-[var(--bg)] text-sm font-medium flex items-center gap-2 disabled:opacity-50"
                  disabled={busy} onClick={agree}>
            <Check size={15} /> {document.requires_agreement ? 'I agree' : 'Continue'}
          </button>
        </div>
      </div>
    </div>
  );
}
