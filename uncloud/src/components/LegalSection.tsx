/** Settings → Legal: what was agreed, when, and whose work is included.
 *
 *  Kept away from the permissions section on purpose. Both are a recorded yes
 *  and they answer different questions — "what did you agree to" against "what
 *  may the agent do right now" — and somebody who confuses them either grants
 *  more than they meant to or looks for a control that is not there.
 */

import { useCallback, useEffect, useState } from 'react';
import { ChevronRight, FileText, Package, X } from 'lucide-react';

import Markdown from './Markdown';
import { getLegalDocument, getLegalState, getThirdPartyNotices,
         type LegalDocument, type LegalState,
         type ThirdPartyNotices } from '../lib/sidecar';

function when(iso: string): string {
  if (!iso) return '';
  const at = new Date(iso);
  return Number.isNaN(at.getTime()) ? iso : at.toLocaleDateString();
}

export default function LegalSection() {
  const [state, setState] = useState<LegalState | null>(null);
  const [reading, setReading] = useState<LegalDocument | null>(null);
  const [notices, setNotices] = useState<ThirdPartyNotices | null>(null);
  const [showNotices, setShowNotices] = useState(false);

  const load = useCallback(() => {
    getLegalState().then(setState).catch(() => undefined);
  }, []);
  useEffect(load, [load]);

  function openNotices() {
    setShowNotices(true);
    if (!notices) getThirdPartyNotices().then(setNotices).catch(() => undefined);
  }

  if (!state) return null;

  return (
    <>
      <section className="card p-4">
        <h2 className="text-sm mb-1">Terms and notices</h2>
        <p className="text-[11px] text-[var(--text-faint)] mb-3">
          What you agreed to, and when. Separate from permissions — agreeing to a
          document has never granted Uncloud anything on this machine.
        </p>

        <div className="flex flex-col gap-2">
          {state.documents.map((doc) => (
            <button key={doc.id}
                    onClick={() => getLegalDocument(doc.id).then(setReading)
                                                           .catch(() => undefined)}
                    className="w-full flex items-center justify-between gap-3 text-left
                               px-3 py-2 rounded-lg hover:bg-[var(--bg-inset)] transition">
              <span className="flex items-center gap-2 min-w-0">
                <FileText size={13} className="text-[var(--text-dim)] shrink-0" />
                <span className="text-xs truncate">{doc.title}</span>
                <span className="text-[10px] font-mono text-[var(--text-faint)] shrink-0">
                  v{doc.version}
                </span>
              </span>
              <span className="flex items-center gap-2 shrink-0">
                <span className="text-[10px] text-[var(--text-faint)]">
                  {doc.accepted
                    ? `Agreed ${when(doc.accepted.accepted_at)}`
                    : doc.requires_agreement ? 'Not agreed' : 'Notice'}
                </span>
                <ChevronRight size={13} className="text-[var(--text-faint)]" />
              </span>
            </button>
          ))}

          <button onClick={openNotices}
                  className="w-full flex items-center justify-between gap-3 text-left
                             px-3 py-2 rounded-lg hover:bg-[var(--bg-inset)] transition">
            <span className="flex items-center gap-2">
              <Package size={13} className="text-[var(--text-dim)]" />
              <span className="text-xs">Open-source notices</span>
            </span>
            <ChevronRight size={13} className="text-[var(--text-faint)]" />
          </button>
        </div>
      </section>

      {reading && (
        <Sheet title={`${reading.title} · v${reading.version}`}
               onClose={() => setReading(null)}>
          <Markdown>{reading.body ?? ''}</Markdown>
        </Sheet>
      )}

      {showNotices && (
        <Sheet title="Open-source notices" onClose={() => setShowNotices(false)}>
          {!notices ? (
            <p className="text-xs text-[var(--text-faint)]">Loading…</p>
          ) : notices.notices.length === 0 ? (
            <p className="text-xs text-[var(--text-dim)] leading-relaxed">
              The notice file is written at build time, so a development build does
              not have one. A release that shipped without it would be a packaging
              failure, and there is a test for that.
            </p>
          ) : (
            <table className="w-full text-xs">
              <thead>
                <tr className="text-[var(--text-faint)] text-left text-[10px] uppercase">
                  <th className="pb-2 font-normal">Component</th>
                  <th className="pb-2 font-normal">Version</th>
                  <th className="pb-2 font-normal">Licence</th>
                </tr>
              </thead>
              <tbody>
                {notices.notices.map((n) => (
                  <tr key={`${n.kind}-${n.name}`}
                      className="border-t border-[var(--border)]">
                    <td className="py-1.5">{n.name}</td>
                    <td className="py-1.5 font-mono text-[var(--text-faint)]">
                      {n.version}
                    </td>
                    <td className={`py-1.5 ${n.complete ? '' : 'text-[var(--text-faint)]'}`}>
                      {n.licence}
                    </td>
                  </tr>
                ))}
              </tbody>
            </table>
          )}
        </Sheet>
      )}
    </>
  );
}

/** A reading panel. Deliberately large: these are documents somebody has to
 *  actually read, and a small scrolling box is how you make sure they do not. */
function Sheet({ title, onClose, children }: {
  title: string; onClose: () => void; children: React.ReactNode;
}) {
  return (
    <div className="modal-backdrop fixed inset-0 z-50 flex items-center justify-center p-8
                    bg-black/50 backdrop-blur-sm" onClick={onClose}>
      <div className="modal-panel card w-full max-w-3xl max-h-[80vh] flex flex-col p-0"
           onClick={(e) => e.stopPropagation()}>
        <div className="flex items-center justify-between gap-3 px-5 py-3
                        border-b border-[var(--border)]">
          <h3 className="text-sm">{title}</h3>
          <button onClick={onClose}
                  className="text-[var(--text-dim)] hover:text-[var(--text)] transition">
            <X size={16} />
          </button>
        </div>
        <div className="overflow-y-auto px-5 py-4 min-h-0">{children}</div>
      </div>
    </div>
  );
}
